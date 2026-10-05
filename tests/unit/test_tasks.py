"""Task inbox, autonomy policy and action lifecycle on a real SQLite file (tmp_path)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.api.db import MIGRATIONS, connect, migrate
from packages.schemas.models import Privacy, TaskIn, TaskPatch
from services.policies.autonomy import Level, decide
from services.router.router import normalize
from services.tasks.store import TaskError, TaskStore
from services.workers.orchestrator import _extract_when


@pytest.fixture
def store(tmp_path):
    con = connect(tmp_path / "ops.db")
    migrate(con)
    return TaskStore(con, "America/Santiago")


def d(n: int, s: TaskStore) -> str:
    return (s.today_date() + timedelta(days=n)).isoformat()


# ----------------------------------------------------------------------------- migration
def test_migration_from_v2_keeps_existing_data_and_is_additive(tmp_path):
    con = connect(tmp_path / "old.db")
    for i, sql in enumerate(MIGRATIONS[:2], start=1):
        con.executescript(f"BEGIN; {sql}; PRAGMA user_version={i}; COMMIT;")
    con.execute("INSERT INTO sessions VALUES ('sid','admin','0',9999999999)")
    assert migrate(con) == len(MIGRATIONS)
    assert con.execute("SELECT username FROM sessions").fetchone()[0] == "admin"
    assert {"tasks", "actions", "task_events"} <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert migrate(con) == len(MIGRATIONS)  # idempotent
    with pytest.raises(Exception):  # CHECK constraints guard states even against buggy code
        con.execute("INSERT INTO actions VALUES ('a','u',NULL,'k','C9','done','user','s','{}',NULL,NULL,'t','t')")


# ----------------------------------------------------------------------------- policy
@pytest.mark.parametrize("tool,origin,kw,level,verdict", [
    ("task.plan_day", "evidence", {}, "C0", "execute"),
    ("task.create", "user", {}, "C1", "execute"),
    ("task.create", "ui", {}, "C1", "execute"),
    ("task.create", "user", {"ambiguous": True}, "C1", "propose"),
    ("task.create", "evidence", {}, "C1", "propose"),      # text found in a log/doc never executes
    ("task.create", "model", {}, "C1", "propose"),
    ("task.create", "user", {"proposed": Level.C0}, "C1", "execute"),  # the model cannot lower the level
    ("task.create", "user", {"proposed": Level.C3}, "C3", "needs_review"),  # ...but it can raise it
    ("email.send", "user", {}, "C3", "needs_review"),       # unknown tool = C3
])
def test_autonomy_policy(tool, origin, kw, level, verdict):
    dec = decide(tool, origin, **kw)
    assert (dec.level.value, dec.verdict) == (level, verdict)


# ----------------------------------------------------------------------------- create / duplicates / idempotency
def test_create_logs_action_and_event(store):
    r = store.create("ana", TaskIn(title="Revisar backup", due_date=d(1, store)), origin="user", actor="ana")
    assert r["action"]["status"] == "done" and r["action"]["level"] == "C1" and not r["duplicate"]
    ev = store.events("ana", r["task"]["task_id"])
    assert ev[0]["op"] == "create" and ev[0]["after"]["title"] == "Revisar backup" and ev[0]["undoable"]


def test_duplicate_title_and_date_is_not_created_twice(store):
    a = store.create("ana", TaskIn(title="Revisar backup", due_date=d(1, store)), origin="user", actor="ana")
    b = store.create("ana", TaskIn(title="  revisar BACKUP ", due_date=d(1, store)), origin="user", actor="ana")
    assert b["duplicate"] and b["task"]["task_id"] == a["task"]["task_id"]
    assert store.list("ana")["total"] == 1
    assert not store.create("ana", TaskIn(title="Revisar backup", due_date=d(2, store)), origin="user", actor="ana")["duplicate"]


def test_concurrent_equal_creates_yield_one_task(store):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda _: store.create("ana", TaskIn(title="Carrera"), origin="user", actor="ana"), range(8)))
    assert store.list("ana")["total"] == 1 and sum(not r["duplicate"] for r in res) == 1
    assert store.con.execute("SELECT COUNT(*) FROM actions WHERE status='done'").fetchone()[0] == 1
    assert store.con.execute("SELECT COUNT(*) FROM actions WHERE status NOT IN ('done','cancelled')").fetchone()[0] == 0


def test_idempotency_key_replays_instead_of_acting_again(store):
    a = store.create("ana", TaskIn(title="Uno"), origin="user", actor="ana", idem_key="k-123456")
    store.update("ana", a["task"]["task_id"], TaskPatch(version=1, title="Uno renombrada"), origin="user", actor="ana")
    b = store.create("ana", TaskIn(title="Uno"), origin="user", actor="ana", idem_key="k-123456")
    assert b["duplicate"] and b["task"]["task_id"] == a["task"]["task_id"]
    assert store.con.execute("SELECT COUNT(*) FROM actions WHERE kind='task.create'").fetchone()[0] == 1


def test_per_user_isolation(store):
    t = store.create("ana", TaskIn(title="Privada de Ana"), origin="user", actor="ana")["task"]
    assert store.list("beto")["total"] == 0
    for call in (lambda: store.get("beto", t["task_id"]),
                 lambda: store.update("beto", t["task_id"], TaskPatch(version=1, title="x"), origin="user", actor="beto"),
                 lambda: store.events("beto", t["task_id"]),
                 lambda: store.undo("beto", store.events("ana", t["task_id"])[0]["event_id"], actor="beto")):
        with pytest.raises(TaskError) as e:
            call()
        assert e.value.status == 404
    with pytest.raises(TaskError):  # parent must be yours
        store.create("beto", TaskIn(title="hija", parent_id=t["task_id"]), origin="user", actor="beto")


# ----------------------------------------------------------------------------- failures and recovery
def test_failure_mid_action_rolls_back_and_is_recorded(store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disco lleno")
    monkeypatch.setattr(store, "_event", boom)  # fails after the task INSERT, inside the same transaction
    with pytest.raises(RuntimeError):
        store.create("ana", TaskIn(title="No debe quedar"), origin="user", actor="ana")
    assert store.list("ana")["total"] == 0
    a = store.actions("ana")[0]
    assert a["status"] == "failed" and a["error"] == "RuntimeError"


def test_reconcile_interrupted_actions_without_rerunning(store):
    ok = store.create("ana", TaskIn(title="Aplicada"), origin="user", actor="ana")
    # Simulate crashes: one action whose change committed, one that never applied.
    store.con.execute("UPDATE actions SET status='running' WHERE action_id=?", (ok["action"]["action_id"],))
    store.con.execute("INSERT INTO actions VALUES ('lost','ana',NULL,'task.create','C1','running','user','x','{}',NULL,NULL,'t','t')")
    assert store.reconcile() == 2
    st = {a["action_id"]: a for a in store.actions("ana")}
    assert st[ok["action"]["action_id"]]["status"] == "done"
    assert st["lost"]["status"] == "failed" and "No se reintenta" in st["lost"]["error"]
    assert store.list("ana")["total"] == 1


def test_failed_idempotency_key_is_not_retried_silently(store):
    store.con.execute("INSERT INTO actions VALUES ('f','ana','k-failed1','task.create','C1','failed','user','x','{}',NULL,'e','t','t')")
    with pytest.raises(TaskError) as e:
        store.create("ana", TaskIn(title="Otra"), origin="user", actor="ana", idem_key="k-failed1")
    assert e.value.status == 409


# ----------------------------------------------------------------------------- update / undo / reorder
def test_update_complete_and_undo(store):
    t = store.create("ana", TaskIn(title="Pagar luz"), origin="user", actor="ana")
    u = store.update("ana", t["task"]["task_id"], TaskPatch(version=1, status="done"), origin="user", actor="ana")
    assert u["task"]["status"] == "done" and u["task"]["completed_at"]
    with pytest.raises(TaskError) as e:  # stale version
        store.update("ana", t["task"]["task_id"], TaskPatch(version=1, title="x"), origin="user", actor="ana")
    assert e.value.status == 409
    back = store.undo("ana", u["event_id"], actor="ana")["task"]
    assert back["status"] == "open" and back["completed_at"] is None
    with pytest.raises(TaskError):  # can't undo twice
        store.undo("ana", u["event_id"], actor="ana")


def test_undo_create_cancels_and_undo_refuses_to_clobber_later_change(store):
    a = store.create("ana", TaskIn(title="A"), origin="user", actor="ana")
    assert store.undo("ana", a["event_id"], actor="ana")["task"]["status"] == "cancelled"
    b = store.create("ana", TaskIn(title="B"), origin="user", actor="ana")
    store.update("ana", b["task"]["task_id"], TaskPatch(version=1, title="B2"), origin="user", actor="ana")
    with pytest.raises(TaskError) as e:
        store.undo("ana", b["event_id"], actor="ana")
    assert e.value.status == 409


def test_reorder_keeps_other_slots_and_undoes_as_a_group(store):
    ids = [store.create("ana", TaskIn(title=t), origin="user", actor="ana")["task"]["task_id"] for t in "ABCD"]
    r = store.reorder("ana", [ids[2], ids[0]], origin="user", actor="ana")  # swap A and C only
    order = [t["title"] for t in store.list("ana")["items"]]
    assert order == ["C", "B", "A", "D"]
    store.undo("ana", r["event_id"], actor="ana")
    assert [t["title"] for t in store.list("ana")["items"]] == ["A", "B", "C", "D"]


# ----------------------------------------------------------------------------- today view
def test_today_buckets_and_explained_recommendations(store):
    mk = lambda title, **kw: store.create("ana", TaskIn(title=title, **kw), origin="user", actor="ana")["task"]
    late = mk("Vencida", due_date=d(-2, store))
    mk("Hoy", due_date=d(0, store), due_time="09:30")
    mk("Pronto", due_date=d(3, store))
    mk("Sin fecha", priority=1)
    mk("Borrador", status="draft", due_date=d(-5, store))
    parent = mk("Migrar servidor")
    mk("Respaldar antes", parent_id=parent["task_id"])
    t = store.today("ana", datetime.combine(store.today_date(), datetime.min.time().replace(hour=8), ZoneInfo(store.tz)))
    assert [x["title"] for x in t["overdue"]] == ["Vencida"]  # drafts never count as overdue
    assert [x["title"] for x in t["today"]] == ["Hoy"]
    assert [x["title"] for x in t["upcoming"]] == ["Pronto"]
    assert [x["title"] for x in t["drafts"]] == ["Borrador"]
    rec = t["recommendations"]
    assert rec[0]["task_id"] == late["task_id"] and "Vencida hace 2 días" in rec[0]["reason"]
    assert "a las 09:30" in rec[1]["reason"]
    assert any("requisito de «Migrar servidor»" in r["reason"] for r in rec)


# ----------------------------------------------------------------------------- dates
@pytest.mark.parametrize("text,days,time", [
    ("para mañana: revisar backup", 1, None), ("hoy a las 9", 0, "09:00"), ("pasado mañana a las 3 pm", 2, "15:00"),
    ("en 10 días", 10, None), ("revisar el backup", None, None), ("llamar por la mañana", None, None),
])
def test_extract_when(text, days, time):
    today = date(2026, 9, 25)  # Friday
    due, hhmm, rest, _ = _extract_when(normalize(text), normalize(text), today)
    assert due == (None if days is None else (today + timedelta(days=days)).isoformat()) and hhmm == time


def test_weekday_is_next_occurrence():
    today = date(2026, 9, 25)  # Friday
    assert _extract_when("el viernes", "el viernes", today)[0] == "2026-10-02"
    assert _extract_when("el lunes", "el lunes", today)[0] == "2026-09-28"


def test_source_privacy_raises_task_privacy_and_bad_sources_rejected(store):
    con = store.con
    con.execute("INSERT INTO documents (document_id, original_name, stored_path, checksum, size_bytes, mime, kind, source, ingested_at,"
                " privacy, verification, owner, status) VALUES ('d1','app.log','x','c',1,'text/plain','log','upload','t','PRIVATE',"
                "'UNVERIFIED','ana','ready')")
    con.execute("INSERT INTO log_events (document_id, line_no, severity, template, message) VALUES ('d1', 7, 'ERROR', 'x', 'db timeout')")
    t = store.create("ana", TaskIn(title="Seguir", privacy=Privacy.PUBLIC, sources=[{"kind": "log", "document_id": "d1", "line": 7}]),
                     origin="evidence", actor="ana")["task"]
    assert t["privacy"] == "PRIVATE" and t["sources"][0]["excerpt"] == "ERROR db timeout" and t["sources"][0]["location"] == "línea 7"
    for bad in ([{"kind": "log", "document_id": "d1", "line": 99}], [{"kind": "log", "document_id": "nope", "line": 1}]):
        with pytest.raises(TaskError):
            store.create("ana", TaskIn(title="x", sources=bad), origin="evidence", actor="ana")
    with pytest.raises(TaskError):  # someone else's document
        store.create("beto", TaskIn(title="x", sources=[{"kind": "log", "document_id": "d1", "line": 7}]), origin="evidence", actor="beto")
    assert json.loads(con.execute("SELECT sources_json FROM tasks").fetchone()[0])[0]["document_id"] == "d1"
