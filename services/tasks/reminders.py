"""Durable logical reminders, snooze generations and bounded recurring catch-up."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from apps.api.db import tx
from services.tasks.store import TaskError
from services.tasks.recurrence import materialize, wall_due

log = logging.getLogger("alice.reminders")
CURRENT = """FROM task_reminders r JOIN tasks t ON t.task_id=r.task_id AND t.owner=r.owner
 WHERE r.owner=? AND t.status IN ('open','in_progress')
 AND t.due_date=r.due_date AND t.due_time=r.due_time AND t.timezone=r.timezone"""
SELECT = """SELECT r.*,t.title FROM task_reminders r
 JOIN tasks t ON t.task_id=r.task_id AND t.owner=r.owner WHERE r.owner=? AND r.reminder_id=?"""


class ReminderService:
    def __init__(self, con, enabled: bool, push=None):
        self.con, self.enabled, self.push = con, enabled, push

    def _event(self, row, kind, now, scheduled=None):
        self.con.execute("INSERT INTO reminder_events(reminder_id,owner,kind,at,generation,scheduled_at) VALUES (?,?,?,?,?,?)",
                         (row['reminder_id'], row['owner'], kind, now.isoformat(), row['generation'], scheduled))

    def _queue(self, row, now):
        if self.push and self.push.enabled:
            self.con.execute("""INSERT OR IGNORE INTO push_deliveries(reminder_id,generation,subscription_id,available_at)
              SELECT ?,?,subscription_id,? FROM push_subscriptions WHERE owner=?
              AND (expiration_ms IS NULL OR expiration_ms>?)""",
              (row['reminder_id'], row['generation'], now.isoformat(), row['owner'], now.timestamp() * 1000))

    def tick(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        fired = 0
        with tx(self.con):
            # Agenda advances even if notification delivery is switched off.
            for series in self.con.execute("SELECT * FROM task_series WHERE active=1 AND cursor_date IS NOT NULL"):
                through = (now.astimezone(ZoneInfo(series['timezone'])).date() + timedelta(days=7)).isoformat()
                materialize(self.con, series, through)
            if not self.enabled:
                return 0
            rows = self.con.execute("""
              SELECT t.* FROM tasks t WHERE t.status IN ('open','in_progress')
              AND t.due_date IS NOT NULL AND t.due_time IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM task_reminders r WHERE r.owner=t.owner AND r.task_id=t.task_id)
              ORDER BY t.due_date,t.due_time LIMIT 1000
            """)
            for task in rows:
                due = wall_due(task['due_date'], task['due_time'], task['timezone'])
                if due > now:
                    continue
                cur = self.con.execute("""INSERT INTO task_reminders
                  (owner,task_id,due_date,due_time,timezone,scheduled_at,fired_at)
                  VALUES (?,?,?,?,?,?,?)""", (task['owner'], task['task_id'], task['due_date'],
                  task['due_time'], task['timezone'], due.isoformat(), now.isoformat()))
                row = self.con.execute("SELECT * FROM task_reminders WHERE reminder_id=?", (cur.lastrowid,)).fetchone()
                self._event(row, 'fired', now, due.isoformat())
                self._queue(row, now)
                fired += 1
            for row in self.con.execute("""SELECT r.* FROM task_reminders r JOIN tasks t
              ON t.task_id=r.task_id AND t.owner=r.owner WHERE r.snoozed_until IS NOT NULL AND r.snoozed_until<=?
              AND t.status IN ('open','in_progress') AND t.due_date=r.due_date AND t.due_time=r.due_time
              AND t.timezone=r.timezone""", (now.isoformat(),)):
                self.con.execute("UPDATE task_reminders SET snoozed_until=NULL,read_at=NULL,fired_at=? WHERE reminder_id=?",
                                 (now.isoformat(), row['reminder_id']))
                self._event(row, 'fired', now, row['snoozed_until'])
                self._queue(row, now)
                fired += 1
        return fired

    def get(self, owner: str, reminder_id: int) -> dict:
        row = self.con.execute(SELECT, (owner, reminder_id)).fetchone()
        if not row:
            raise TaskError(404, 'Recordatorio no encontrado')
        out = dict(row)
        out.pop('owner')
        out['history'] = [dict(r) for r in self.con.execute(
            'SELECT event_id,kind,at,generation,scheduled_at FROM reminder_events WHERE owner=? AND reminder_id=? ORDER BY event_id',
            (owner, reminder_id))]
        return out

    def list(self, owner: str, limit: int = 20) -> dict:
        rows = self.con.execute('SELECT r.*,t.title ' + CURRENT +
          ' ORDER BY r.read_at IS NOT NULL,r.fired_at DESC,r.reminder_id DESC LIMIT ?',
          (owner, max(1, min(limit, 100))))
        items = [{k: r[k] for k in r.keys() if k != 'owner'} for r in rows]
        unread = self.con.execute('SELECT COUNT(*) ' + CURRENT +
          ' AND r.read_at IS NULL AND r.snoozed_until IS NULL', (owner,)).fetchone()[0]
        return {'enabled': self.enabled, 'unread': unread, 'items': items}

    def acknowledge(self, owner: str, reminder_id: int) -> dict:
        with tx(self.con):
            row = self.con.execute('SELECT r.* ' + CURRENT + ' AND r.reminder_id=?', (owner, reminder_id)).fetchone()
            if row is None:
                raise TaskError(404, 'Recordatorio no encontrado')
            if not row['read_at'] or row['snoozed_until']:
                now = datetime.now(timezone.utc)
                self.con.execute('UPDATE task_reminders SET read_at=?,snoozed_until=NULL WHERE owner=? AND reminder_id=?',
                                 (now.isoformat(), owner, reminder_id))
                if not row['read_at']:
                    self._event(row, 'read', now)
                self.con.execute("UPDATE push_deliveries SET status='cancelled' WHERE reminder_id=? AND status IN ('pending','sending')",
                                 (reminder_id,))
        return {'ok': True}

    def snooze(self, owner: str, reminder_id: int, *, minutes=None, until=None, now=None) -> dict:
        now = now or datetime.now(timezone.utc)
        if (minutes is None) == (until is None) or (minutes is not None and minutes not in (10, 60)):
            raise TaskError(422, 'Indica minutes 10/60 o until con zona')
        try:
            due = now + timedelta(minutes=minutes) if minutes is not None else datetime.fromisoformat(until)
            if due.tzinfo is None or due.utcoffset() is None or due <= now:
                raise ValueError()
            due = due.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError) as exc:
            raise TaskError(422, 'until debe ser una fecha futura con zona horaria') from exc
        with tx(self.con):
            self.get(owner, reminder_id)
            row = self.con.execute('SELECT r.* ' + CURRENT + ' AND r.reminder_id=?', (owner, reminder_id)).fetchone()
            if row is None:
                raise TaskError(409, 'La tarea ya terminó o cambió de horario')
            if row['snoozed_until'] != due:
                self.con.execute('UPDATE task_reminders SET snoozed_until=?,generation=generation+1,read_at=? WHERE reminder_id=? AND owner=?',
                                 (due, now.isoformat(), reminder_id, owner))
                row = self.con.execute('SELECT * FROM task_reminders WHERE reminder_id=?', (reminder_id,)).fetchone()
                self._event(row, 'snoozed', now, due)
                self.con.execute("UPDATE push_deliveries SET status='cancelled' WHERE reminder_id=? AND status IN ('pending','sending')", (reminder_id,))
        return self.get(owner, reminder_id)

    async def loop(self, interval: float = 15.0) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.exception('No se pudo revisar los recordatorios')
            await asyncio.sleep(interval)
