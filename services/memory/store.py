"""Per-user on/off toggle for local long-term memory (Hindsight). Missing row = enabled (the default)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from apps.api.db import tx


def memory_enabled_for(con: sqlite3.Connection, owner: str) -> bool:
    row = con.execute("SELECT enabled FROM memory_prefs WHERE owner=?", (owner,)).fetchone()
    return bool(row["enabled"]) if row else True


def set_memory_enabled(con: sqlite3.Connection, owner: str, enabled: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with tx(con):
        con.execute(
            "INSERT INTO memory_prefs(owner, enabled, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(owner) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at",
            (owner, int(enabled), now))
