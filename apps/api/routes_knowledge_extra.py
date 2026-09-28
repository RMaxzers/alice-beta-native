"""Knowledge-area extras owned by this workstream:

A. GET /api/datasets/{document_id}/rows — read-only rows for the Univer spreadsheet viewer.
B. NotebookLM (unofficial CLI, C2, off by default): status + a preview/authorize/send flow for both
   "add a document as a source" and "ask a question", reusing EgressGate exactly like the chat
   egress-consent flow (ticket -> user approves via the existing /api/egress/{id}/approve -> single-use
   clearance bound to user/provider/model/payload hash/cost/expiry).

Every C2 action is recorded in `actions` (docs/AUTONOMY.md): a row is created `awaiting_authorization`
at preview time (its `idem_key` is the ticket id, so `send` can find it back), moves to `running` right
before the CLI call, and only reaches `done` once the CLI itself returns a successful, parsed response —
never optimistically.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.db import tx
from apps.api.security import require_user
from packages.schemas.models import EgressPreview, Privacy
from services.integrations import notebooklm
from services.policies.autonomy import level_for
from services.policies.egress import EgressDenied, payload_hash
from services.structured_data.sql import q

router = APIRouter()

ROWS_DEFAULT = 500
ROWS_HARD_CAP = 5000


# ============================================================================ A. spreadsheet viewer (Univer)
@router.get("/api/datasets/{document_id}/rows")
async def dataset_rows(document_id: str, request: Request, limit: int = Query(ROWS_DEFAULT, ge=1, le=ROWS_HARD_CAP),
                       user: str = Depends(require_user)):
    st = request.app.state.alice
    ds = st.con.execute("SELECT table_name, columns_json, row_count FROM datasets WHERE document_id=? AND owner=?",
                        (document_id, user)).fetchone()
    if not ds:
        raise HTTPException(404, "Conjunto de datos no encontrado")
    columns = json.loads(ds["columns_json"])
    con = sqlite3.connect(f"file:{Path(st.settings.tables_db).as_posix()}?mode=ro", uri=True)
    try:
        rows = [list(r) for r in con.execute(f"SELECT * FROM {q(ds['table_name'])} LIMIT ?", (limit,)).fetchall()]
    finally:
        con.close()
    return {"columns": columns, "rows": rows, "total": ds["row_count"], "truncated": len(rows) < ds["row_count"]}


# ============================================================================ B. NotebookLM (optional, C2)
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_enabled(st) -> None:
    if not st.settings.notebooklm_enabled:
        raise HTTPException(403, "NotebookLM está deshabilitado. Actívalo con NOTEBOOKLM_ENABLED=true en tu .env")
    if st.local_only:
        raise HTTPException(403, "Modo «Solo local» activo: no se ofrecen envíos a NotebookLM")


def _begin_action(con: sqlite3.Connection, owner: str, kind: str, summary: str, payload_in: dict, idem_key: str) -> str:
    aid, now = uuid.uuid4().hex, _now()
    with tx(con):
        con.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, owner, idem_key, kind, level_for(kind).value, "awaiting_authorization", "ui", summary,
                     json.dumps(payload_in, ensure_ascii=False), None, None, now, now))
    return aid


def _find_action(con: sqlite3.Connection, owner: str, ticket_id: str, kind: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM actions WHERE owner=? AND idem_key=? AND kind=?", (owner, ticket_id, kind)).fetchone()
    if not row:
        raise HTTPException(404, "No se encontró la solicitud de envío para este ticket")
    return row


def _mark_running(con: sqlite3.Connection, action_id: str) -> None:
    with tx(con):
        con.execute("UPDATE actions SET status='running', updated_at=? WHERE action_id=?", (_now(), action_id))


def _finish_action(con: sqlite3.Connection, action_id: str, status: str, *, error: str | None = None, summary: str | None = None) -> None:
    with tx(con):
        if summary is None:
            con.execute("UPDATE actions SET status=?, error=?, updated_at=? WHERE action_id=?", (status, error, _now(), action_id))
        else:
            con.execute("UPDATE actions SET status=?, error=?, summary=?, updated_at=? WHERE action_id=?",
                        (status, error, summary, _now(), action_id))


REVERT_SOURCE = "Borra esta fuente en NotebookLM (Fuentes -> eliminar) para quitarla del notebook."
REVERT_ASK = "La pregunta queda en el historial de conversación de NotebookLM; bórrala desde «Historial» si quieres eliminarla."


@router.get("/api/integrations/notebooklm/status")
async def notebooklm_status(request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    if not st.settings.notebooklm_enabled:
        return {"enabled": False, "installed": False, "logged_in": False,
                "detail": "Deshabilitado: activa NOTEBOOKLM_ENABLED=true en tu .env"}
    s = await notebooklm.status(st.settings.notebooklm_cli)
    return {"enabled": True, **s}


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    notebook: str = Field(min_length=1, max_length=200)


@router.post("/api/integrations/notebooklm/preview")
async def notebooklm_preview(body: PreviewBody, request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    _require_enabled(st)
    doc = st.con.execute("SELECT * FROM documents WHERE document_id=? AND owner=?", (body.document_id, user)).fetchone()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    payload = {"action": "notebooklm.add_source", "document_id": doc["document_id"], "notebook": body.notebook, "checksum": doc["checksum"]}
    try:
        tid = st.gate.request_ticket(user, "notebooklm", "source.add", payload, max_cost_usd=0)
    except EgressDenied as e:
        raise HTTPException(403, e.detail) from e
    _begin_action(st.con, user, "notebooklm.add_source", f"Enviar «{doc['original_name']}» a NotebookLM",
                 {"document_id": doc["document_id"], "notebook": body.notebook}, idem_key=tid)
    preview = EgressPreview(provider="notebooklm", recipients=["Google NotebookLM (cuenta de Google del usuario)"],
                            model="source.add", reason="Enviar el documento a un notebook de NotebookLM para resumirlo y preguntarle",
                            privacy=Privacy(doc["privacy"]), fields=["El archivo completo del documento"],
                            payload_preview=f"Documento «{doc['original_name']}» ({doc['size_bytes']} bytes) → notebook «{body.notebook}»",
                            payload_hash=payload_hash(payload), estimated_cost_usd=None, max_cost_usd=0, ticket_request_id=tid)
    return {**preview.model_dump(mode="json"),
            "document": {"document_id": doc["document_id"], "name": doc["original_name"], "size_bytes": doc["size_bytes"]},
            "how_to_revert": REVERT_SOURCE}


class TicketBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_id: str


@router.post("/api/integrations/notebooklm/send")
async def notebooklm_send(body: TicketBody, request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    _require_enabled(st)
    action = _find_action(st.con, user, body.ticket_id, "notebooklm.add_source")
    if action["status"] in ("done", "failed", "cancelled"):
        raise HTTPException(409, "Esta autorización ya se usó")
    payload_in = json.loads(action["input_json"])
    doc = st.con.execute("SELECT * FROM documents WHERE document_id=? AND owner=?", (payload_in["document_id"], user)).fetchone()
    if not doc:
        _finish_action(st.con, action["action_id"], "failed", error="Documento no encontrado")
        raise HTTPException(404, "Documento no encontrado")
    payload = {"action": "notebooklm.add_source", "document_id": doc["document_id"], "notebook": payload_in["notebook"], "checksum": doc["checksum"]}
    try:
        st.gate.clear(username=user, provider="notebooklm", model="source.add", payload=payload,
                      privacy=Privacy(doc["privacy"]), ticket_id=body.ticket_id)
    except EgressDenied as e:
        _finish_action(st.con, action["action_id"], "failed", error=e.detail)
        raise HTTPException(409, e.detail) from e
    base = (st.settings.data_dir / "raw").resolve()
    p = (st.settings.data_dir / doc["stored_path"]).resolve()
    if base not in p.parents:
        _finish_action(st.con, action["action_id"], "failed", error="Ruta de archivo inválida")
        raise HTTPException(404)
    _mark_running(st.con, action["action_id"])
    try:
        result = await notebooklm.add_document(payload_in["notebook"], p, cli=st.settings.notebooklm_cli)
    except notebooklm.NotebookLMError as e:
        _finish_action(st.con, action["action_id"], "failed", error=str(e))
        raise HTTPException(502, str(e)) from e
    _finish_action(st.con, action["action_id"], "done", summary=f"Fuente añadida a NotebookLM: {doc['original_name']}")
    return {"ok": True, "result": result}


class AskPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notebook: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)


@router.post("/api/integrations/notebooklm/ask/preview")
async def notebooklm_ask_preview(body: AskPreviewBody, request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    _require_enabled(st)
    payload = {"action": "notebooklm.ask", "notebook": body.notebook, "question": body.question}
    try:
        tid = st.gate.request_ticket(user, "notebooklm", "ask", payload, max_cost_usd=0)
    except EgressDenied as e:
        raise HTTPException(403, e.detail) from e
    _begin_action(st.con, user, "notebooklm.ask", f"Preguntar a NotebookLM: «{body.question[:60]}»",
                 {"notebook": body.notebook, "question": body.question}, idem_key=tid)
    preview = EgressPreview(provider="notebooklm", recipients=["Google NotebookLM (cuenta de Google del usuario)"],
                            model="ask", reason="Preguntar a un notebook de NotebookLM sobre sus fuentes",
                            privacy=Privacy.PRIVATE, fields=["El texto de la pregunta"],
                            payload_preview=body.question[:500], payload_hash=payload_hash(payload),
                            estimated_cost_usd=None, max_cost_usd=0, ticket_request_id=tid)
    return {**preview.model_dump(mode="json"), "how_to_revert": REVERT_ASK}


@router.post("/api/integrations/notebooklm/ask/send")
async def notebooklm_ask_send(body: TicketBody, request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    _require_enabled(st)
    action = _find_action(st.con, user, body.ticket_id, "notebooklm.ask")
    if action["status"] in ("done", "failed", "cancelled"):
        raise HTTPException(409, "Esta autorización ya se usó")
    payload_in = json.loads(action["input_json"])
    payload = {"action": "notebooklm.ask", "notebook": payload_in["notebook"], "question": payload_in["question"]}
    try:
        st.gate.clear(username=user, provider="notebooklm", model="ask", payload=payload, privacy=Privacy.PRIVATE, ticket_id=body.ticket_id)
    except EgressDenied as e:
        _finish_action(st.con, action["action_id"], "failed", error=e.detail)
        raise HTTPException(409, e.detail) from e
    _mark_running(st.con, action["action_id"])
    try:
        result = await notebooklm.ask(payload_in["notebook"], payload_in["question"], cli=st.settings.notebooklm_cli)
    except notebooklm.NotebookLMError as e:
        _finish_action(st.con, action["action_id"], "failed", error=str(e))
        raise HTTPException(502, str(e)) from e
    _finish_action(st.con, action["action_id"], "done", summary="Pregunta respondida por NotebookLM")
    return {"ok": True, "result": result}
