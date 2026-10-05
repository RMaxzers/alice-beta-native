"""Calendar rules in wall time. UTC is only used at the notification boundary."""
from __future__ import annotations

import calendar
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def wall_due(day: str, clock: str, tz: str) -> datetime:
    # fold=0 picks the earlier instant in a fold, and shifts forward by the gap.
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ZoneInfo(tz), fold=0).astimezone(timezone.utc)


def next_date(day: str, anchor: str, rule: dict) -> str | None:
    d = date.fromisoformat(day)
    try:
        if rule["freq"] == "monthly":
            year, month = d.year + (d.month == 12), d.month % 12 + 1
            d = date(year, month, min(date.fromisoformat(anchor).day, calendar.monthrange(year, month)[1]))
        else:
            d += timedelta(days=1)
            if rule["freq"] == "weekly":
                while d.isoweekday() not in rule["weekdays"]:
                    d += timedelta(days=1)
    except (OverflowError, ValueError):
        return None
    result = d.isoformat()
    return None if rule.get("until") and result > rule["until"] else result


def validate_start(day: str | None, status: str, rule: dict) -> None:
    from services.tasks.store import TaskError
    if not day or status != "open":
        raise TaskError(422, "Una serie necesita fecha inicial y estado open")
    if rule.get("until") and rule["until"] < day:
        raise TaskError(422, "until no puede ser anterior al inicio")
    if rule["freq"] == "weekly" and date.fromisoformat(day).isoweekday() not in rule["weekdays"]:
        raise TaskError(422, "La fecha inicial debe ser uno de los días seleccionados")


def attach(con, task: dict, rule: dict) -> None:
    """Inside the task action transaction. Save an immutable series template."""
    validate_start(task["due_date"], task["status"], rule)
    sid = uuid.uuid4().hex
    encoded = json.dumps(rule)
    task.update(series_id=sid, occurrence_date=task["due_date"], recurrence_json=encoded)
    con.execute("INSERT INTO task_series VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, task["owner"], encoded, task["due_date"], task["timezone"], json.dumps(task),
                 next_date(task["due_date"], task["due_date"], rule), 1, task["created_at"]))
    con.execute("UPDATE tasks SET series_id=?,occurrence_date=?,recurrence_json=? WHERE task_id=?",
                (sid, task["due_date"], encoded, task["task_id"]))


def materialize(con, series, through: str, limit: int = 256) -> int:
    """Caller owns BEGIN IMMEDIATE. Cursor and occurrences commit together."""
    if not series["active"]:
        return 0
    day, rule = series["cursor_date"], json.loads(series["recurrence_json"])
    count = 0
    while day and day <= through and count < limit:
        task = json.loads(series["template_json"])
        now = datetime.now(timezone.utc).isoformat()
        task.update(task_id=uuid.uuid4().hex, due_date=day, occurrence_date=day, status="open",
                    created_at=now, updated_at=now, completed_at=None, version=1, action_id=None)
        # Deterministic series slot, independent of how many times a worker restarts.
        task["position"] += (date.fromisoformat(day) - date.fromisoformat(series["start_date"])).days / 100000
        cols = list(task)
        cur = con.execute(f"INSERT OR IGNORE INTO tasks ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                          [task[k] for k in cols])
        if cur.rowcount:
            task['task_id'] = con.execute("SELECT task_id FROM tasks WHERE series_id=? AND occurrence_date=?",
                                           (series['series_id'], day)).fetchone()[0]
            con.execute("""INSERT INTO task_events(task_id,owner,at,actor,origin,op,after_json)
              VALUES (?,?,?,'alice-worker','schedule','occurrence',?)""",
              (task['task_id'], series['owner'], now, json.dumps(task, ensure_ascii=False)))
        day = next_date(day, series["start_date"], rule)
        count += 1
    con.execute("UPDATE task_series SET cursor_date=? WHERE series_id=?", (day, series["series_id"]))
    return count
