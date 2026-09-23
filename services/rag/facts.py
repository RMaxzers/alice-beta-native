"""Verified/empirical facts. The LLM can never set VERIFIED; conflicts are surfaced, never silently resolved."""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from apps.api.db import tx
from packages.schemas.models import Privacy, Verification


class FactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_key: str = Field(min_length=2, max_length=120, description="Stable key, e.g. 'servicio-demo.puerto'")
    statement: str = Field(min_length=3, max_length=1000)
    privacy: Privacy = Privacy.INTERNAL
    verification: Verification
    source_id: str = Field(min_length=1, max_length=200)
    source_location: str | None = None
    verified_by: str | None = None
    valid_until: str | None = None
    notes: str | None = None


def norm_key(k: str) -> str:
    return re.sub(r"\s+", "-", k.strip().lower())


def add_fact(con: sqlite3.Connection, f: FactIn, actor: str, *, via_llm: bool = False) -> dict:
    if via_llm and f.verification == Verification.VERIFIED:
        raise ValueError("Un LLM no puede otorgar VERIFIED")
    if f.verification == Verification.VERIFIED and not f.verified_by:
        raise ValueError("VERIFIED requiere verified_by (validación humana o procedimiento auditable)")
    now = datetime.now(timezone.utc).isoformat()
    row = {"fact_id": uuid.uuid4().hex[:12], **f.model_dump(mode="json"), "subject_key": norm_key(f.subject_key), "owner": actor,
           "verified_at": now if f.verification != Verification.UNVERIFIED else None, "created_at": now}
    row["verified_by"] = f.verified_by or (actor if f.verification != Verification.UNVERIFIED else None)
    with tx(con):
        con.execute(f"INSERT INTO facts({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    return row


def facts_for(con: sqlite3.Connection, subject_key: str, owner: str) -> dict:
    """Returns the owner's facts for a subject plus any VERIFIED conflicts (different statements, both VERIFIED)."""
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM facts WHERE owner=? AND subject_key=? AND (valid_until IS NULL OR valid_until > ?) "
        "ORDER BY CASE verification WHEN 'VERIFIED' THEN 0 WHEN 'EMPIRICAL' THEN 1 ELSE 2 END, verified_at DESC",
        (owner, norm_key(subject_key), datetime.now(timezone.utc).isoformat()))]
    verified = [r for r in rows if r["verification"] == "VERIFIED"]
    distinct = {r["statement"].strip().lower() for r in verified}
    conflict = verified if len(distinct) > 1 else []
    return {"facts": rows, "conflict": conflict}


def search_facts(con: sqlite3.Connection, text: str, owner: str, limit: int = 5) -> list[dict]:
    words = [w for w in re.findall(r"\w{4,}", text.lower())][:8]
    if not words:
        return []
    clause = " OR ".join(["LOWER(statement) LIKE ? OR subject_key LIKE ?"] * len(words))
    params = [p for w in words for p in (f"%{w}%", f"%{w}%")]
    return [dict(r) for r in con.execute(f"SELECT * FROM facts WHERE owner=? AND ({clause}) LIMIT {int(limit)}", [owner, *params])]
