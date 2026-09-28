"""Local long-term memory (Hindsight sidecar). Memories are private, local data: recall/list/status are
C0 reads; forget (soft-invalidate) and the on/off toggle are C1 local, reversible changes (see
docs/AUTONOMY.md, services/policies/autonomy.py TOOL_LEVEL). Bank isolation IS user isolation: the bank id
is always derived from the authenticated session (never from client input), so a memory_id belonging to
another user's bank simply does not exist here.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from apps.api.db import tx
from apps.api.security import require_user
from services.memory import hindsight
from services.memory.store import memory_enabled_for, set_memory_enabled

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _audit(con, actor: str, target: str, outcome: str, t0: float) -> None:
    with tx(con):
        con.execute("INSERT INTO audit(at, actor, action, target, outcome, duration_ms) VALUES (?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), actor, "memory.forget", target, outcome,
                     int((time.perf_counter() - t0) * 1000)))


@router.get("/status")
async def status(request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    user_on = memory_enabled_for(st.con, user)
    healthy = await hindsight.health(st.settings.hindsight_url)
    count = None
    if healthy:
        try:
            count = (await hindsight.list_memories(st.settings.hindsight_url, user, limit=1))["total"]
        except hindsight.MemoryUnavailable:
            count = None
    return {"enabled": st.settings.memory_enabled and user_on, "user_enabled": user_on,
            "sidecar_healthy": healthy, "count": count}


@router.get("")
async def list_memory(request: Request, q: str | None = None, limit: int = 50, user: str = Depends(require_user)):
    st = request.app.state.alice
    try:
        return await hindsight.list_memories(st.settings.hindsight_url, user, q=q, limit=max(1, min(limit, 200)))
    except hindsight.MemoryUnavailable as e:
        raise HTTPException(503, str(e)) from e


class ToggleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.post("/toggle")
async def toggle(body: ToggleIn, request: Request, user: str = Depends(require_user)):
    set_memory_enabled(request.app.state.alice.con, user, body.enabled)
    return {"enabled": body.enabled}


@router.delete("/{memory_id}")
async def forget(memory_id: str, request: Request, user: str = Depends(require_user)):
    st = request.app.state.alice
    t0 = time.perf_counter()
    try:
        await hindsight.forget(st.settings.hindsight_url, user, memory_id)
    except hindsight.MemoryUnavailable as e:
        _audit(st.con, user, memory_id, "error", t0)
        raise HTTPException(503, str(e)) from e
    _audit(st.con, user, memory_id, "ok", t0)
    return {"forgotten": memory_id}
