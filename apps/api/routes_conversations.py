from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.api.security import require_user
from packages.schemas.models import ChatRequest, Privacy
from services.actions.files import ActionError, FileInput, chat_filename
from services.conversations.store import ConversationError

router = APIRouter()


def call(fn):
    try:
        return fn()
    except (ConversationError, ActionError) as e:
        raise HTTPException(e.status, e.detail) from e


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Nueva conversación", min_length=1, max_length=200)
    privacy: Privacy = Privacy.PRIVATE


@router.get("/api/identity")
async def identity(request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    return {"backend_id": st.conversations.backend_id, "executor_name": st.file_executor.executor_name,
            "api_contract": "1", "file_action": {"enabled": st.file_executor.root is not None, "root_label": "Mi carpeta de Alice"}}


@router.get("/api/conversations")
async def conversations(request: Request, limit: int = 50, offset: int = 0, user: str = Depends(require_user)):
    return request.app.state.alice.conversations.list(user, max(1, min(limit, 200)), max(0, offset))


@router.post("/api/conversations", status_code=201)
async def create_conversation(body: ConversationInput, request: Request, user: str = Depends(require_user)):
    return request.app.state.alice.conversations.create(user, body.title, body.privacy)


@router.get("/api/conversations/{cid}")
async def conversation(cid: str, request: Request, user: str = Depends(require_user)):
    return call(lambda: request.app.state.alice.conversations.get(user, cid))


@router.post("/api/file-actions")
async def file_action(body: FileInput, request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    privacy = call(lambda: st.conversations.raise_privacy(user, body.conversation_id, body.privacy))
    body = body.model_copy(update={"privacy": privacy})
    result = call(lambda: st.file_executor.create(user, body))
    # The operation remains retrievable even when no success can be asserted.
    if result["status"] == "failed":
        raise HTTPException(409, {"message": result["error"], "operation_id": result["operation_id"]})
    return result


@router.get("/api/file-actions/{operation_id}")
async def file_operation(operation_id: str, request: Request, user: str = Depends(require_user)):
    return call(lambda: request.app.state.alice.file_executor.get(user, operation_id))


@router.get("/api/file-actions")
async def file_operations(request: Request, conversation_id: str | None = None, limit: int = 100,
                          user: str = Depends(require_user)):
    st = request.app.state.alice
    sql, args = "SELECT * FROM file_operations WHERE owner=?", [user]
    if conversation_id:
        call(lambda: st.conversations.get(user, conversation_id, messages=False))
        sql += " AND conversation_id=?"
        args.append(conversation_id)
    args.append(max(1, min(limit, 200)))
    return [st.file_executor.public(r) for r in st.con.execute(sql + " ORDER BY created_at DESC LIMIT ?", args)]


async def action_events(st, req, user, filename):
    history = st.conversations.get(user, req.conversation_id)["messages"]
    answers = [m for m in history if m["role"] == "assistant" and m["status"] == "complete"]
    if not answers:
        yield {"type": "error", "code": "no_summary", "message": "Esta conversación todavía no tiene una respuesta completa que guardar."}
        return
    try:
        body = FileInput(conversation_id=req.conversation_id, client_request_id=req.client_request_id,
                         filename=filename, content=answers[-1]["content"], privacy=req.privacy)
        result = st.file_executor.create(user, body)
        ok = result["status"] == "done"
        message = (f"Archivo creado y verificado: {result['destination']} en {result['executor_name']}. "
                   f"Operación {result['operation_id']}." if ok else
                   f"Operación {result['operation_id']} en {result['executor_name']}: {result['error'] or result['status']}.")
        yield {"type": "action", "action": result, "file_action": result, "message": message}
        if not ok:
            yield {"type": "error", "code": "action_unverified", "message": message}
    except (ActionError, ValidationError) as e:
        yield {"type": "error", "code": "file_action", "message": e.detail if isinstance(e, ActionError) else "Nombre de archivo inválido"}


async def persistent_chat(req: ChatRequest, request: Request, user: str):
    st = request.app.state.alice
    turn, clean, replay = call(lambda: st.conversations.prepare(user, req))

    async def stream():
        if replay is not None:
            for ev in replay:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
            return
        privacy, events, outcome = clean.privacy, [], "interrupted"
        first = {"type": "conversation", "conversation_id": turn["conversation_id"],
                 "client_request_id": turn["client_request_id"], "privacy": privacy.value}
        events.append(first)
        source = None
        try:
            yield json.dumps(first, ensure_ascii=False) + "\n"
            filename = chat_filename(clean.message)
            source = action_events(st, clean, user, filename) if filename else st.orchestrator.chat(clean, user)
            outcome = "complete"
            done = None
            async for ev in source:
                if await request.is_disconnected():
                    outcome = "interrupted"
                    break
                levels = [privacy]
                if ev.get("privacy"):
                    levels.append(Privacy(ev["privacy"]))
                if ev["type"] == "route":
                    levels.append(Privacy(ev["decision"]["privacy"]))
                if ev["type"] == "sources":
                    levels.extend(Privacy(s.get("privacy", "PRIVATE")) for s in ev["sources"])
                raised = Privacy.strictest(*levels)
                if raised != privacy:
                    privacy = st.conversations.raise_privacy(user, clean.conversation_id, raised)
                if ev["type"] == "done":
                    done = ev
                    continue
                if ev["type"] == "error":
                    outcome = "failed"
                elif ev["type"] == "authorization_required":
                    outcome = "awaiting_authorization"
                events.append(ev)
                yield json.dumps(ev, ensure_ascii=False) + "\n"
            # Persist before final done is visible to the client.
            final = {**(done or {}), "type": "done", "conversation_id": clean.conversation_id,
                     "client_request_id": clean.client_request_id, "privacy": privacy.value, "status": outcome}
            if outcome == "complete":
                events.append(final)
            st.conversations.finish(user, turn, events, privacy, outcome)
            send_done = outcome == "complete"
            outcome = "stored"
            if send_done:
                yield json.dumps(final, ensure_ascii=False) + "\n"
        finally:
            try:
                if source is not None:
                    await source.aclose()
            finally:
                if outcome != "stored":
                    st.conversations.finish(user, turn, events, privacy, "interrupted")

    return StreamingResponse(stream(), media_type="application/x-ndjson")
