"""Persistent local reminders: collect due tasks even when no browser is open."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from zoneinfo import ZoneInfo

from apps.api.db import tx
from services.tasks.store import TaskError

log = logging.getLogger("alice.reminders")
CURRENT = """FROM task_reminders r JOIN tasks t ON t.task_id=r.task_id AND t.owner=r.owner
 WHERE r.owner=? AND t.status IN ('open','in_progress')
 AND t.due_date=r.due_date AND t.due_time=r.due_time AND t.timezone=r.timezone"""


class ReminderService:
    def __init__(self, con, enabled: bool):
        self.con = con
        self.enabled = enabled

    def tick(self) -> int:
        if not self.enabled:
            return 0
        now = datetime.now(timezone.utc)
        fired = 0
        with tx(self.con):
            rows = self.con.execute("""
              SELECT t.* FROM tasks t WHERE t.status IN ('open','in_progress')
              AND t.due_date IS NOT NULL AND t.due_time IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM task_reminders r WHERE r.owner=t.owner
               AND r.task_id=t.task_id AND r.due_date=t.due_date AND r.due_time=t.due_time
               AND r.timezone=t.timezone)
              ORDER BY t.due_date,t.due_time LIMIT 1000
            """)
            for task in rows:
                # On a DST gap, converting the wall time to UTC delivers after the gap;
                # an ambiguous repeated time uses fold=0 and the unique key fires once.
                due = datetime.fromisoformat(f"{task['due_date']}T{task['due_time']}")
                due = due.replace(tzinfo=ZoneInfo(task["timezone"])).astimezone(timezone.utc)
                if due > now:
                    continue
                self.con.execute("""INSERT OR IGNORE INTO task_reminders
                  (owner,task_id,due_date,due_time,timezone,scheduled_at,fired_at)
                  VALUES (?,?,?,?,?,?,?)""", (task["owner"], task["task_id"], task["due_date"],
                  task["due_time"], task["timezone"], due.isoformat(), now.isoformat()))
                fired += 1
        return fired

    def list(self, owner: str, limit: int = 20) -> dict:
        rows = self.con.execute("""SELECT r.reminder_id,r.task_id,t.title,r.due_date,
          r.due_time,r.timezone,r.scheduled_at,r.fired_at,r.read_at """ + CURRENT +
          " ORDER BY r.read_at IS NOT NULL,r.fired_at DESC,r.reminder_id DESC LIMIT ?",
          (owner, max(1, min(limit, 100))))
        unread = self.con.execute("SELECT COUNT(*) " + CURRENT + " AND r.read_at IS NULL", (owner,)).fetchone()[0]
        return {"enabled": self.enabled, "unread": unread, "items": [dict(row) for row in rows]}

    def acknowledge(self, owner: str, reminder_id: int) -> dict:
        with tx(self.con):
            row = self.con.execute("SELECT r.reminder_id " + CURRENT + " AND r.reminder_id=?",
                                   (owner, reminder_id)).fetchone()
            if row is None:
                raise TaskError(404, "Recordatorio no encontrado")
            self.con.execute("UPDATE task_reminders SET read_at=COALESCE(read_at,?) WHERE owner=? AND reminder_id=?",
                             (datetime.now(timezone.utc).isoformat(), owner, reminder_id))
        return {"ok": True}

    async def loop(self, interval: float = 15.0) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.exception("No se pudo revisar los recordatorios")
            await asyncio.sleep(interval)
