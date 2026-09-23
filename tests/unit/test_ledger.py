"""§11.5 cost ledger on real SQLite (tmp_path): atomic reservation, daily limit under concurrency, retries, unknown != 0."""
from __future__ import annotations

import threading

import httpx
import pytest

from apps.api.db import connect, migrate
from services.providers.ledger import BudgetExceeded, Ledger


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "ops.db"
    migrate(connect(path))
    return path


def ledger(db, per=0.05, daily=1.0):
    return Ledger(connect(db), per, daily, "America/Santiago")


def test_per_request_cap_and_unknown_estimate(db):
    L = ledger(db)
    with pytest.raises(BudgetExceeded, match="por petición"):
        L.reserve("r", "CLOUD_CHEAP", "openrouter", "m", 0.051)
    with pytest.raises(BudgetExceeded, match="estimar"):
        L.reserve("r", "CLOUD_CHEAP", "openrouter", "m", None)
    assert L.spent_today()["calls"] == 0


@pytest.mark.parametrize("shared_connection", [True, False])
def test_daily_limit_holds_under_concurrency(db, shared_connection):
    """40 concurrent reservations of 0.04 against a 1.00 daily budget: exactly 25 may succeed."""
    shared = ledger(db)
    ok, denied, errors = [], [], []
    barrier = threading.Barrier(40)

    def worker(i):
        L = shared if shared_connection else ledger(db)
        barrier.wait()
        try:
            ok.append(L.reserve(f"r{i}", "CLOUD_CHEAP", "openrouter", "m", 0.04))
        except BudgetExceeded:
            denied.append(i)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == [] and len(ok) == 25 and len(denied) == 15
    assert shared.spent_today()["reserved_open"] == pytest.approx(1.0)


def test_unknown_cost_is_not_zero_and_keeps_reservation(db):
    L = ledger(db, daily=0.10)
    a = L.reserve("r1", "CLOUD_CHEAP", "openrouter", "m", 0.05)
    L.reconcile(a, 100, None, None)  # provider did not report cost
    s = L.spent_today()
    assert s["unknown_cost_calls"] == 1 and s["reserved_open"] == pytest.approx(0.05)
    L.reserve("r2", "CLOUD_CHEAP", "openrouter", "m", 0.05)
    with pytest.raises(BudgetExceeded):
        L.reserve("r3", "CLOUD_CHEAP", "openrouter", "m", 0.01)


def test_reported_cost_replaces_reservation_and_zero_is_a_known_value(db):
    L = ledger(db)
    a = L.reserve("r1", "CLOUD_CHEAP", "openrouter", "m", 0.05)
    L.reconcile(a, 10, 5, 0.002)
    b = L.reserve("r2", "CLOUD_CHEAP", "openrouter", "m", 0.05)
    L.reconcile(b, 10, 5, 0.0)
    s = L.spent_today()
    assert s["accounted"] == pytest.approx(0.002) and s["reserved_open"] == 0 and s["unknown_cost_calls"] == 0


def test_retries_each_reserve_and_failed_attempts_release(db):
    L = ledger(db, daily=0.10)
    for i in range(5):  # five retried attempts that failed before any billing
        L.release(L.reserve("r1", "CLOUD_CHEAP", "openrouter", "m", 0.05))
    assert L.spent_today()["reserved_open"] == 0 and L.spent_today()["calls"] == 5
    a = L.reserve("r1", "CLOUD_CHEAP", "openrouter", "m", 0.05)
    L.reconcile(a, 1, 1, 0.01)
    L.reconcile(a, 1, 1, 0.01)  # double reconciliation does not double count
    L.release(a)  # releasing a reconciled attempt is a no-op
    assert L.spent_today()["accounted"] == pytest.approx(0.01)


# ------------------------------------------------------------------ via the real orchestrator (fake OpenRouter receiver)
def _cloud(api, net, handler):
    base = net.handlers["openrouter.ai:443"]
    net.handlers["openrouter.ai:443"] = lambda req: base(req) if req.url.path.endswith("/models") else handler(req)
    return api.chat(message="hola", privacy="PUBLIC", force_route="CLOUD_CHEAP")


def test_failure_before_tokens_releases(api, state, net):
    ev = _cloud(api, net, lambda req: httpx.Response(503, text="overloaded"))
    assert ev[-1]["type"] == "error"
    assert [r["state"] for r in state.con.execute("SELECT state FROM ledger")] == ["released"]


def test_failure_mid_stream_is_unknown_cost_not_zero(api, state, net):
    sse = 'data: {"choices":[{"delta":{"content":"parcial"}}]}\n\ndata: {"error":{"message":"upstream died"}}\n\n'
    ev = _cloud(api, net, lambda req: httpx.Response(200, content=sse.encode()))
    assert ev[-1]["type"] == "error"
    row = state.con.execute("SELECT * FROM ledger").fetchone()
    assert row["state"] == "unknown_cost" and row["reported_usd"] is None and row["reserved_usd"] > 0


def test_success_reconciles_reported_cost(api, state, net):
    ev = api.chat(message="hola", privacy="PUBLIC", force_route="CLOUD_CHEAP")
    assert ev[-1]["type"] == "done" and ev[-1]["cost_usd"] == pytest.approx(0.00001) and ev[-1]["cost_state"] == "reported"
    row = state.con.execute("SELECT * FROM ledger").fetchone()
    assert row["state"] == "reconciled" and row["tokens_in"] == 12


def test_unpriced_model_is_never_called(api, state, net):
    net.handlers["openrouter.ai:443"] = lambda req: httpx.Response(200, json={"data": []})
    ev = api.chat(message="hola", privacy="PUBLIC", force_route="CLOUD_CHEAP")
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "budget"
    assert net.external_posts() == []
