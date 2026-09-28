"""/api/memory/*: auth required, CSRF on mutations, per-user bank isolation. The Hindsight sidecar is a
small stateful fake receiver on 127.0.0.1:8888 (the `net` fixture); these tests never touch the real one,
so they pass with the sidecar down."""
from __future__ import annotations

import json

import httpx
import pytest

from services.memory import hindsight
from tests.security.test_api_security import as_user

MEMORY_ENDPOINTS = [("GET", "/api/memory/status"), ("GET", "/api/memory"), ("POST", "/api/memory/toggle"), ("DELETE", "/api/memory/x")]


class FakeHindsight:
    """Minimal stateful stand-in for the sidecar: one dict of memories per bank (path-derived bank id)."""

    def __init__(self):
        self.banks: dict[str, dict[str, dict]] = {}
        self._seq = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        parts = request.url.path.split("/")
        bank_id, rest = parts[4], "/".join(parts[5:])
        bank = self.banks.setdefault(bank_id, {})
        if rest == "memories" and request.method == "POST":
            body = json.loads(request.content)
            n = 0
            for item in body["items"]:
                self._seq += 1
                mid = f"m{self._seq}"
                bank[mid] = {"id": mid, "text": item["content"], "context": item.get("context", ""),
                            "date": item.get("timestamp") or "", "state": "valid"}
                n += 1
            return httpx.Response(200, json={"success": True, "bank_id": bank_id, "items_count": n, "async": body.get("async", False)})
        if rest == "memories/list" and request.method == "GET":
            items = [v for v in bank.values() if v["state"] == "valid"]
            q = request.url.params.get("q")
            if q:
                items = [v for v in items if q.lower() in v["text"].lower()]
            return httpx.Response(200, json={"items": items, "total": len(items), "limit": 50, "offset": 0})
        if rest == "memories/recall" and request.method == "POST":
            items = [v for v in bank.values() if v["state"] == "valid"]
            return httpx.Response(200, json={"results": items[:5]})
        if rest.startswith("memories/") and request.method == "PATCH":
            mid = rest.split("/", 1)[1]
            if mid not in bank:
                return httpx.Response(404, json={"detail": "not found"})
            bank[mid].update(json.loads(request.content))
            return httpx.Response(200, json=bank[mid])
        return httpx.Response(404)


@pytest.fixture
def fake_hindsight(net):
    f = FakeHindsight()
    net.handlers["127.0.0.1:8888"] = f
    return f


# ----------------------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", MEMORY_ENDPOINTS)
def test_memory_endpoints_require_session(client, method, path):
    r = client.request(method, path, json={"enabled": True} if path.endswith("toggle") else None)
    assert r.status_code == 401


# ----------------------------------------------------------------------------- CSRF
def test_toggle_requires_csrf(api, fake_hindsight):
    assert api.c.post("/api/memory/toggle", json={"enabled": False}).status_code == 403
    assert api.c.post("/api/memory/toggle", json={"enabled": False}, headers=api.h()).status_code == 200


def test_forget_requires_csrf(api, fake_hindsight):
    assert api.c.delete("/api/memory/m1").status_code == 403
    # CSRF accepted -> the sidecar 404s an unknown id (mapped to 503) instead of a 403
    assert api.c.delete("/api/memory/m1", headers=api.h()).status_code == 503


# ----------------------------------------------------------------------------- status / toggle
def test_status_reports_health_and_toggle_state(api, fake_hindsight):
    body = api.c.get("/api/memory/status", headers=api.h()).json()
    assert body["sidecar_healthy"] is True and body["enabled"] is True and body["user_enabled"] is True

    r = api.c.post("/api/memory/toggle", json={"enabled": False}, headers=api.h())
    assert r.status_code == 200 and r.json()["enabled"] is False
    body = api.c.get("/api/memory/status", headers=api.h()).json()
    assert body["user_enabled"] is False and body["enabled"] is False


def test_status_reports_sidecar_down(api):
    # no fake receiver registered for 127.0.0.1:8888 -> the `net` fixture answers 599 for any request there
    body = api.c.get("/api/memory/status", headers=api.h()).json()
    assert body["sidecar_healthy"] is False and body["count"] is None


def test_toggle_rejects_unknown_fields(api, fake_hindsight):
    assert api.c.post("/api/memory/toggle", json={"enabled": True, "extra": 1}, headers=api.h()).status_code == 422


# ----------------------------------------------------------------------------- list / forget happy path
async def test_list_and_forget_happy_path(api, fake_hindsight):
    await hindsight.retain("http://127.0.0.1:8888", "admin", "al usuario le gusta el café solo")
    items = api.c.get("/api/memory", headers=api.h()).json()["items"]
    assert len(items) == 1 and "café solo" in items[0]["text"]

    mid = items[0]["id"]
    assert api.c.delete(f"/api/memory/{mid}", headers=api.h()).status_code == 200
    assert api.c.get("/api/memory", headers=api.h()).json()["items"] == []  # invalidated -> drops out of list


async def test_forget_is_audited(api, state, fake_hindsight):
    await hindsight.retain("http://127.0.0.1:8888", "admin", "dato a olvidar")
    mid = api.c.get("/api/memory", headers=api.h()).json()["items"][0]["id"]
    api.c.delete(f"/api/memory/{mid}", headers=api.h())
    row = state.con.execute("SELECT * FROM audit WHERE action='memory.forget' AND target=?", (mid,)).fetchone()
    assert row is not None and row["actor"] == "admin" and row["outcome"] == "ok"


# ----------------------------------------------------------------------------- user isolation
async def test_one_users_bank_never_used_for_another(api, state, fake_hindsight):
    await hindsight.retain("http://127.0.0.1:8888", "admin", "secreto de admin")
    other, h = as_user(state, "intruso")

    assert other.get("/api/memory", headers=h).json()["items"] == []

    admin_mid = api.c.get("/api/memory", headers=api.h()).json()["items"][0]["id"]
    # intruso forges admin's memory_id: the bank is derived from *their own* session, so it just isn't there
    assert other.delete(f"/api/memory/{admin_mid}", headers=h).status_code == 503
    assert api.c.get("/api/memory", headers=api.h()).json()["items"][0]["id"] == admin_mid  # admin's memory untouched
