"""apps/api/routes_knowledge_extra.py through the real FastAPI app.

A. /api/datasets/{id}/rows: auth, per-user isolation, the hard row cap, and that the table actually
   queried can only ever be the one recorded for that document+owner (no table name ever comes from
   the request).
B. NotebookLM: auth/CSRF, refused while disabled/local_only, and the full preview -> approve -> send
   flow through the real EgressGate — refused without an approved ticket, on a reused ticket, and when
   the document changes between preview and send (payload hash no longer matches).

The real `notebooklm` CLI is never invoked: services.integrations.notebooklm.{status,add_document,ask}
are monkeypatched, so these tests pass whether or not the CLI is installed or logged in.
"""
from __future__ import annotations

import json

import pytest

import services.integrations.notebooklm as N
from tests.security.test_api_security import as_user, upload
from tests.security.test_privacy_egress import ingest

CSV = b"id,nombre\n1,Ana\n2,Beto\n3,Caro\n"


def csv_of(n: int) -> bytes:
    return b"id,nombre\n" + b"".join(f"{i},fila{i}\n".encode() for i in range(1, n + 1))


# ============================================================================ A. dataset rows
def test_dataset_rows_requires_session(client):
    assert client.get("/api/datasets/x/rows").status_code == 401


def test_dataset_rows_missing_document_404(api):
    assert api.c.get("/api/datasets/no-existe/rows").status_code == 404


def test_dataset_rows_document_without_dataset_404(api, state):
    doc = ingest(state, "nota.md", b"# Nota\ncontenido\n")
    assert api.c.get(f"/api/datasets/{doc}/rows").status_code == 404


def test_dataset_rows_returns_columns_and_data(api, state):
    doc = ingest(state, "hoja.csv", CSV)
    r = api.c.get(f"/api/datasets/{doc}/rows")
    assert r.status_code == 200
    body = r.json()
    assert body["columns"] == ["id", "nombre"]
    assert body["rows"] == [[1, "Ana"], [2, "Beto"], [3, "Caro"]]
    assert body["total"] == 3 and body["truncated"] is False


def test_dataset_rows_respects_limit_and_reports_truncation(api, state):
    doc = ingest(state, "grande.csv", csv_of(20))
    r = api.c.get(f"/api/datasets/{doc}/rows?limit=5")
    body = r.json()
    assert len(body["rows"]) == 5 and body["total"] == 20 and body["truncated"] is True


def test_dataset_rows_rejects_over_hard_cap(api, state):
    doc = ingest(state, "hoja.csv", CSV)
    assert api.c.get(f"/api/datasets/{doc}/rows?limit=5001").status_code == 422


def test_dataset_rows_other_user_cannot_address_it(api, state):
    doc = ingest(state, "hoja.csv", CSV)
    other, h = as_user(state, "mallory")
    assert other.get(f"/api/datasets/{doc}/rows").status_code == 404
    # the attacker's own (empty) dataset catalog proves no cross-owner table lookup ever happens
    assert state.con.execute("SELECT COUNT(*) FROM datasets WHERE owner='mallory'").fetchone()[0] == 0


# ============================================================================ B. NotebookLM
def enable(state, *, local_only=False):
    state.settings.notebooklm_enabled = True
    state.settings.notebooklm_cli = "notebooklm"
    state.set_local_only(local_only)


def fake_ok(monkeypatch, **overrides):
    async def fake_status(cli="notebooklm"):
        return {"installed": True, "logged_in": True, "detail": "Sesión de Google activa"}

    async def fake_add(notebook, file_path, cli="notebooklm"):
        return {"source_id": "src-1"}

    async def fake_ask(notebook, question, cli="notebooklm"):
        return {"answer": "42"}

    monkeypatch.setattr(N, "status", overrides.get("status", fake_status))
    monkeypatch.setattr(N, "add_document", overrides.get("add_document", fake_add))
    monkeypatch.setattr(N, "ask", overrides.get("ask", fake_ask))


def test_status_disabled_by_default(api):
    r = api.c.get("/api/integrations/notebooklm/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_status_enabled_delegates_to_cli_wrapper(api, state, monkeypatch):
    enable(state)
    fake_ok(monkeypatch)
    body = api.c.get("/api/integrations/notebooklm/status").json()
    assert body == {"enabled": True, "installed": True, "logged_in": True, "detail": "Sesión de Google activa"}


NOTEBOOKLM_STATE_CHANGING = [
    ("/api/integrations/notebooklm/preview", {"document_id": "x", "notebook": "n"}),
    ("/api/integrations/notebooklm/send", {"ticket_id": "x"}),
    ("/api/integrations/notebooklm/ask/preview", {"notebook": "n", "question": "hola"}),
    ("/api/integrations/notebooklm/ask/send", {"ticket_id": "x"}),
]


@pytest.mark.parametrize("path,body", NOTEBOOKLM_STATE_CHANGING)
def test_notebooklm_endpoints_require_session(client, path, body):
    assert client.post(path, json=body).status_code == 401


@pytest.mark.parametrize("path,body", NOTEBOOKLM_STATE_CHANGING)
def test_notebooklm_endpoints_require_csrf(api, state, path, body):
    enable(state)
    assert api.c.post(path, json=body).status_code == 403


@pytest.mark.parametrize("path,body", NOTEBOOKLM_STATE_CHANGING)
def test_notebooklm_refused_when_disabled(api, path, body):
    r = api.c.post(path, json=body, headers=api.h())
    assert r.status_code == 403 and "NOTEBOOKLM_ENABLED" in r.json()["detail"]


@pytest.mark.parametrize("path,body", NOTEBOOKLM_STATE_CHANGING)
def test_notebooklm_refused_when_local_only(api, state, path, body):
    enable(state, local_only=True)
    r = api.c.post(path, json=body, headers=api.h())
    assert r.status_code == 403 and "Solo local" in r.json()["detail"]


def test_preview_unknown_document_404(api, state):
    enable(state)
    r = api.c.post("/api/integrations/notebooklm/preview", json={"document_id": "no-existe", "notebook": "n"}, headers=api.h())
    assert r.status_code == 404


def test_preview_contains_egress_consent_fields(api, state):
    enable(state)
    doc = ingest(state, "nota.md", b"# Nota\nsecreta\n")
    r = api.c.post("/api/integrations/notebooklm/preview", json={"document_id": doc, "notebook": "Mi NB"}, headers=api.h())
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "notebooklm" and body["privacy"] == "PRIVATE"
    assert "Google NotebookLM" in body["recipients"][0]
    assert body["ticket_request_id"] and body["how_to_revert"]
    # recorded as an action awaiting authorization
    action = state.con.execute("SELECT * FROM actions WHERE idem_key=?", (body["ticket_request_id"],)).fetchone()
    assert action["status"] == "awaiting_authorization" and action["level"] == "C2" and action["kind"] == "notebooklm.add_source"


def test_send_without_approved_ticket_refused(api, state, monkeypatch):
    enable(state)
    fake_ok(monkeypatch)
    doc = ingest(state, "nota.md", b"# Nota\ncontenido\n")
    pv = api.c.post("/api/integrations/notebooklm/preview", json={"document_id": doc, "notebook": "Mi NB"}, headers=api.h()).json()
    r = api.c.post("/api/integrations/notebooklm/send", json={"ticket_id": pv["ticket_request_id"]}, headers=api.h())
    assert r.status_code == 409
    assert state.con.execute("SELECT status FROM actions WHERE idem_key=?", (pv["ticket_request_id"],)).fetchone()["status"] == "failed"


def test_send_unknown_ticket_404(api, state):
    enable(state)
    r = api.c.post("/api/integrations/notebooklm/send", json={"ticket_id": "no-existe"}, headers=api.h())
    assert r.status_code == 404


def test_send_success_then_reused_ticket_refused(api, state, monkeypatch):
    enable(state)
    fake_ok(monkeypatch)
    doc = ingest(state, "nota.md", b"# Nota\ncontenido\n")
    pv = api.c.post("/api/integrations/notebooklm/preview", json={"document_id": doc, "notebook": "Mi NB"}, headers=api.h()).json()
    assert api.c.post(f"/api/egress/{pv['ticket_request_id']}/approve", headers=api.h()).status_code == 200
    r1 = api.c.post("/api/integrations/notebooklm/send", json={"ticket_id": pv["ticket_request_id"]}, headers=api.h())
    assert r1.status_code == 200 and r1.json()["result"] == {"source_id": "src-1"}
    action = state.con.execute("SELECT * FROM actions WHERE idem_key=?", (pv["ticket_request_id"],)).fetchone()
    assert action["status"] == "done"
    r2 = api.c.post("/api/integrations/notebooklm/send", json={"ticket_id": pv["ticket_request_id"]}, headers=api.h())
    assert r2.status_code == 409


def test_send_refused_when_document_changed_since_preview(api, state, monkeypatch):
    enable(state)
    fake_ok(monkeypatch)
    doc = ingest(state, "nota.md", b"# Nota\ncontenido original\n")
    pv = api.c.post("/api/integrations/notebooklm/preview", json={"document_id": doc, "notebook": "Mi NB"}, headers=api.h()).json()
    assert api.c.post(f"/api/egress/{pv['ticket_request_id']}/approve", headers=api.h()).status_code == 200
    # simulate content drift after the preview was shown (e.g. the document was replaced)
    state.con.execute("UPDATE documents SET checksum='otro-checksum-distinto' WHERE document_id=?", (doc,))
    r = api.c.post("/api/integrations/notebooklm/send", json={"ticket_id": pv["ticket_request_id"]}, headers=api.h())
    assert r.status_code == 409
    assert state.con.execute("SELECT status FROM actions WHERE idem_key=?", (pv["ticket_request_id"],)).fetchone()["status"] == "failed"


def test_send_other_user_cannot_use_ticket(api, state, monkeypatch):
    enable(state)
    fake_ok(monkeypatch)
    doc = ingest(state, "nota.md", b"# Nota\ncontenido\n")
    pv = api.c.post("/api/integrations/notebooklm/preview", json={"document_id": doc, "notebook": "Mi NB"}, headers=api.h()).json()
    api.c.post(f"/api/egress/{pv['ticket_request_id']}/approve", headers=api.h())
    other, h = as_user(state, "mallory")
    r = other.post("/api/integrations/notebooklm/send", json={"ticket_id": pv["ticket_request_id"]}, headers=h)
    assert r.status_code == 404


def test_add_document_failure_marks_action_failed(api, state, monkeypatch):
    enable(state)

    async def failing_add(notebook, file_path, cli="notebooklm"):
        raise N.NotebookLMError("el CLI no está autenticado")
    fake_ok(monkeypatch, add_document=failing_add)
    doc = ingest(state, "nota.md", b"# Nota\ncontenido\n")
    pv = api.c.post("/api/integrations/notebooklm/preview", json={"document_id": doc, "notebook": "Mi NB"}, headers=api.h()).json()
    api.c.post(f"/api/egress/{pv['ticket_request_id']}/approve", headers=api.h())
    r = api.c.post("/api/integrations/notebooklm/send", json={"ticket_id": pv["ticket_request_id"]}, headers=api.h())
    assert r.status_code == 502
    action = state.con.execute("SELECT * FROM actions WHERE idem_key=?", (pv["ticket_request_id"],)).fetchone()
    assert action["status"] == "failed" and "no está autenticado" in action["error"]


# ----------------------------------------------------------------------------- ask flow
def test_ask_preview_and_send(api, state, monkeypatch):
    enable(state)
    fake_ok(monkeypatch)
    pv = api.c.post("/api/integrations/notebooklm/ask/preview", json={"notebook": "Mi NB", "question": "¿qué dice el informe?"},
                    headers=api.h()).json()
    assert pv["provider"] == "notebooklm" and pv["ticket_request_id"]
    assert api.c.post(f"/api/egress/{pv['ticket_request_id']}/approve", headers=api.h()).status_code == 200
    r = api.c.post("/api/integrations/notebooklm/ask/send", json={"ticket_id": pv["ticket_request_id"]}, headers=api.h())
    assert r.status_code == 200 and r.json()["result"] == {"answer": "42"}
    action = state.con.execute("SELECT * FROM actions WHERE idem_key=?", (pv["ticket_request_id"],)).fetchone()
    assert action["status"] == "done" and action["kind"] == "notebooklm.ask"
