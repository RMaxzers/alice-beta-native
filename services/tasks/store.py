"""Task inbox + executed actions. Every C1 change goes through `_run`, which gives it:
an `actions` row (idempotency key, state), one atomic transaction for the change and its task_events
(before/after for undo), and a recorded failure instead of a silent one.

Crash safety: the action row is committed as `running` BEFORE the change; the change and `done` commit together.
A `running` row found at startup is reconciled against the tasks table, never re-executed blindly.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apps.api.db import tx
from packages.schemas.models import Privacy, SourceRef, TaskIn, TaskPatch
from services.policies.autonomy import level_for
from services.router.router import normalize
from services.tasks.recurrence import attach, materialize, next_date, wall_due

OPEN = ("draft", "open", "in_progress")
PRIORITY = {1: "urgente", 2: "alta", 3: "normal", 4: "baja"}
TASK_FIELDS = ("title", "description", "status", "priority", "kind", "due_date", "due_time", "project", "parent_id")


class _Duplicate(Exception):
    def __init__(self, row):
        super().__init__("duplicate")
        self.row = row


class TaskError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["sources"] = json.loads(d.pop("sources_json"))
    d.pop("owner", None)
    d.pop("action_id", None)
    d["recurrence"] = json.loads(d.pop("recurrence_json", None) or "null")
    following = next_date(d["occurrence_date"], d["occurrence_date"], d["recurrence"]) if d.get("series_id") else None
    d["next_due"] = {"due_date": following, "due_time": d["due_time"]} if following else None
    d["due_at"] = (wall_due(d['due_date'], d['due_time'], d['timezone']).astimezone(ZoneInfo(d['timezone'])).isoformat()
                   if d["due_date"] and d["due_time"] else None)
    return d


def _action(r: sqlite3.Row) -> dict:
    d = dict(r)
    d.pop("input_json", None)
    d.pop("owner", None)
    d.pop("idem_key", None)
    return d


class TaskStore:
    def __init__(self, con: sqlite3.Connection, tz: str):
        self.con = con
        self.tz = tz

    # ------------------------------------------------------------------ reads (C0)
    def today_date(self) -> date:
        return datetime.now(ZoneInfo(self.tz)).date()

    def get(self, owner: str, task_id: str) -> dict:
        t = _task(self.con.execute("SELECT * FROM tasks WHERE task_id=? AND owner=?", (task_id, owner)).fetchone())
        if not t:
            raise TaskError(404, "Tarea no encontrada")
        if t.get("series_id"):
            series = self.series(owner, t["series_id"])
            following = next_date(t["occurrence_date"], series["start_date"], t["recurrence"]) if series["active"] else None
            t["next_due"] = {"due_date": following, "due_time": t["due_time"]} if following else None
        return t

    def series(self, owner: str, series_id: str) -> dict:
        row = self.con.execute("SELECT * FROM task_series WHERE series_id=? AND owner=?", (series_id, owner)).fetchone()
        if not row:
            raise TaskError(404, "Serie no encontrada")
        return {"series_id": series_id, "recurrence": json.loads(row["recurrence_json"]),
                "active": bool(row["active"]), "timezone": row["timezone"], "start_date": row["start_date"]}

    def stop_series(self, owner: str, series_id: str) -> dict:
        with tx(self.con):
            self.series(owner, series_id)
            now = datetime.now(timezone.utc)
            self.con.execute("UPDATE task_series SET active=0 WHERE owner=? AND series_id=?", (owner, series_id))
            for row in self.con.execute("SELECT * FROM tasks WHERE owner=? AND series_id=? AND status IN ('open','in_progress')", (owner, series_id)):
                future = (wall_due(row["due_date"], row["due_time"], row["timezone"]) > now if row["due_time"]
                          else row["due_date"] > now.astimezone(ZoneInfo(row["timezone"])).date().isoformat())
                if future:
                    self.con.execute("UPDATE tasks SET status='cancelled',version=version+1,updated_at=? WHERE task_id=?", (_utc(), row["task_id"]))
                    self._event(owner, row["task_id"], None, owner, "user", "series_stop", dict(row), self._row(row["task_id"]))
        return {"ok": True}

    def daily_summary(self, owner: str, day: date | None = None, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(ZoneInfo(self.tz)).date()
        day = day or today
        end = (day + timedelta(days=7)).isoformat()
        groups = {"overdue": [], "today": [], "upcoming": []}
        for row in self.con.execute("SELECT * FROM tasks WHERE owner=? AND status IN ('open','in_progress')", (owner,)):
            t = self.get(owner, row["task_id"])
            due = t["due_date"]
            if due and (due < day.isoformat() or (day == today and due == day.isoformat() and t["due_at"] and datetime.fromisoformat(t["due_at"]) <= now)):
                groups["overdue"].append(t)
            elif due is None or due == day.isoformat():
                groups["today"].append(t)
            elif day.isoformat() < due <= end:
                groups["upcoming"].append(t)
        for items in groups.values():
            items.sort(key=lambda t: (t["due_date"] or "9999", t["due_time"] or "23:59", t["priority"], t["task_id"]))
        ordered = groups["overdue"] + groups["today"] + groups["upcoming"]
        return {"date": day.isoformat(), "timezone": self.tz, "generated_at": now.isoformat(),
                "counts": {"pending": len(groups["today"]), "overdue": len(groups["overdue"]), "upcoming": len(groups["upcoming"])},
                "next": ordered[0] if ordered else None, **{k: v[:5] for k, v in groups.items()}}

    def list(self, owner: str, statuses: list[str] | None = None, limit: int = 50, offset: int = 0) -> dict:
        statuses = statuses or list(OPEN)
        q = f"FROM tasks WHERE owner=? AND status IN ({','.join('?' * len(statuses))})"
        total = self.con.execute("SELECT COUNT(*) " + q, [owner, *statuses]).fetchone()[0]
        rows = self.con.execute("SELECT * " + q + " ORDER BY position LIMIT ? OFFSET ?", [owner, *statuses, limit, offset])
        return {"items": [self.get(owner, r["task_id"]) for r in rows], "total": total}

    def find_open(self, owner: str, text: str) -> list[dict]:
        """Open tasks whose title contains `text` (accent/case-insensitive)."""
        n = normalize(text).strip()
        if not n:
            return []
        rows = self.con.execute(f"SELECT * FROM tasks WHERE owner=? AND status IN {OPEN} ORDER BY position", (owner,))
        return [self.get(owner, r["task_id"]) for r in rows if n in normalize(r["title"])]

    def events(self, owner: str, task_id: str) -> list[dict]:
        self.get(owner, task_id)
        rows = self.con.execute("SELECT * FROM task_events WHERE task_id=? AND owner=? ORDER BY event_id DESC", (task_id, owner))
        out = []
        for r in rows:
            d = dict(r)
            d.pop("owner")
            d["before"] = json.loads(d.pop("before_json") or "null")
            d["after"] = json.loads(d.pop("after_json") or "null")
            is_series_create = d["op"] == "create" and bool((d["after"] or {}).get("series_id"))
            d["undoable"] = d["undone_at"] is None and d["op"] not in ("undo", "occurrence", "series_stop") and not is_series_create
            out.append(d)
        return out

    def actions(self, owner: str, limit: int = 20) -> list[dict]:
        return [_action(r) for r in self.con.execute(
            "SELECT * FROM actions WHERE owner=? ORDER BY created_at DESC LIMIT ?", (owner, limit))]

    def today(self, owner: str, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        d0 = now.astimezone(ZoneInfo(self.tz)).date()
        iso, week = d0.isoformat(), (d0 + timedelta(days=7)).isoformat()
        rows = [self.get(owner, r["task_id"]) for r in self.con.execute(
            f"SELECT * FROM tasks WHERE owner=? AND status IN {OPEN} ORDER BY position", (owner,))]
        active = [t for t in rows if t["status"] != "draft"]
        overdue = [t for t in active if t["due_date"] and (t["due_date"] < iso or
                   (t["due_date"] == iso and t["due_at"] and datetime.fromisoformat(t["due_at"]) <= now))]
        overdue_ids = {t["task_id"] for t in overdue}
        out = {"date": iso, "timezone": self.tz,
               "overdue": overdue,
               "today": [t for t in active if t["due_date"] == iso and t["task_id"] not in overdue_ids],
               "upcoming": [t for t in active if t["due_date"] and iso < t["due_date"] <= week],
               "undated": [t for t in active if not t["due_date"]],
               "drafts": [t for t in rows if t["status"] == "draft"],
               "recent_actions": self.actions(owner, 10)}
        out["recommendations"] = self._recommend(active, d0)
        return out

    def _recommend(self, active: list[dict], d0: date) -> list[dict]:
        """Deterministic, explainable order: overdue first, then due today, prerequisites, priority, closeness."""
        by_id = {t["task_id"]: t for t in active}
        scored = []
        for t in active:
            reasons, score = [], 0.0
            if t["due_date"]:
                days = (date.fromisoformat(t["due_date"]) - d0).days
                if days < 0:
                    score += 100 + min(-days, 30)
                    reasons.append(f"vencida hace {-days} día{'s' if days != -1 else ''}")
                elif days == 0:
                    score += 80
                    reasons.append("vence hoy" + (f" a las {t['due_time']}" if t["due_time"] else ""))
                elif days <= 3:
                    score += 40 - days * 5
                    reasons.append(f"vence en {days} día{'s' if days != 1 else ''}")
            parent = by_id.get(t["parent_id"] or "")
            if parent:
                score += 15
                reasons.append(f"es requisito de «{parent['title']}»")
            if t["priority"] <= 2:
                score += (3 - t["priority"]) * 20
                reasons.append(f"prioridad {PRIORITY[t['priority']]}")
            if reasons:
                scored.append((score, t, reasons))
        scored.sort(key=lambda x: (-x[0], x[1]["position"]))
        out = []
        for i, (_, t, r) in enumerate(scored[:5]):
            reason = "; ".join(r)
            out.append({"rank": i + 1, "task_id": t["task_id"], "title": t["title"], "reason": reason[:1].upper() + reason[1:]})
        return out

    # ------------------------------------------------------------------ evidence
    def resolve_sources(self, owner: str, refs: list[SourceRef]) -> tuple[list[dict], Privacy]:
        """Every cited source must exist and belong to the owner; excerpts are read from our own DB."""
        out, privs = [], []
        for ref in refs:
            doc = self.con.execute("SELECT document_id, original_name, kind, privacy FROM documents WHERE document_id=? AND owner=?",
                                   (ref.document_id, owner)).fetchone()
            if not doc:
                raise TaskError(422, "Fuente no encontrada entre tus documentos")
            src = {"kind": ref.kind, "document_id": doc["document_id"], "title": doc["original_name"], "location": None,
                   "excerpt": None, "privacy": doc["privacy"]}
            if ref.kind == "log":
                if doc["kind"] != "log" or ref.line is None:
                    raise TaskError(422, "La fuente de log necesita un documento de log y una línea")
                ev = self.con.execute("SELECT line_no, severity, message FROM log_events WHERE document_id=? AND line_no=?",
                                      (doc["document_id"], ref.line)).fetchone()
                if not ev:
                    raise TaskError(422, f"La línea {ref.line} no existe en ese log")
                src.update(location=f"línea {ev['line_no']}", line=ev["line_no"],
                           excerpt=f"{ev['severity'] or ''} {ev['message']}".strip()[:300])
            out.append(src)
            privs.append(Privacy(doc["privacy"]))
        return out, Privacy.strictest(*privs) if privs else Privacy.PUBLIC

    # ------------------------------------------------------------------ writes (C1) — all through _run
    def _begin(self, owner: str, kind: str, origin: str, summary: str, payload: dict, idem_key: str | None,
               dedupe=None) -> tuple[dict, str]:
        """Returns (row, mode): mode "new" (action row), "replay" (earlier action, same idempotency key) or
        "dup" (existing task found by `dedupe`). The checks and the insert share the write lock, so they are atomic."""
        with tx(self.con):
            if idem_key:
                prev = self.con.execute("SELECT * FROM actions WHERE owner=? AND idem_key=?", (owner, idem_key)).fetchone()
                if prev:
                    return dict(prev), "replay"
            if dedupe and (hit := dedupe()):
                return dict(hit), "dup"
            aid, now = uuid.uuid4().hex, _utc()
            self.con.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (aid, owner, idem_key, kind, level_for(kind).value, "running", origin, summary,
                              json.dumps(payload, ensure_ascii=False), None, None, now, now))
        return dict(self.con.execute("SELECT * FROM actions WHERE action_id=?", (aid,)).fetchone()), "new"

    def _run(self, owner: str, kind: str, origin: str, summary: str, payload: dict, idem_key: str | None, fn, dedupe=None):
        """fn(action_id) performs the change inside one transaction and returns (task_id, result). -> (row, result, mode)"""
        action, mode = self._begin(owner, kind, origin, summary, payload, idem_key, dedupe)
        if mode != "new":
            return action, None, mode
        try:
            with tx(self.con):
                task_id, result = fn(action["action_id"])
                self.con.execute("UPDATE actions SET status='done', task_id=?, summary=?, updated_at=? WHERE action_id=?",
                                 (task_id, summary, _utc(), action["action_id"]))
        except _Duplicate as d:  # found while holding the write lock: record why nothing was done
            with tx(self.con):
                self.con.execute("UPDATE actions SET status='cancelled', error=?, updated_at=? WHERE action_id=?",
                                 ("Ya existía una tarea igual; no se creó otra", _utc(), action["action_id"]))
            return dict(d.row), None, "dup"
        except Exception as e:
            err = e.detail if isinstance(e, TaskError) else f"{type(e).__name__}"
            with tx(self.con):
                self.con.execute("UPDATE actions SET status='failed', error=?, updated_at=? WHERE action_id=?",
                                 (err, _utc(), action["action_id"]))
            raise
        return _action(self.con.execute("SELECT * FROM actions WHERE action_id=?", (action["action_id"],)).fetchone()), result, "new"

    def _event(self, owner, task_id, action_id, actor, origin, op, before, after) -> int:
        cur = self.con.execute(
            "INSERT INTO task_events(task_id, owner, action_id, at, actor, origin, op, before_json, after_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, owner, action_id, _utc(), actor, origin, op,
             json.dumps(before, ensure_ascii=False) if before else None, json.dumps(after, ensure_ascii=False) if after else None))
        return cur.lastrowid

    def _row(self, task_id: str) -> dict:
        return dict(self.con.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def _check_parent(self, owner: str, parent_id: str | None, task_id: str | None = None) -> None:
        if parent_id is None:
            return
        if parent_id == task_id or not self.con.execute("SELECT 1 FROM tasks WHERE task_id=? AND owner=?", (parent_id, owner)).fetchone():
            raise TaskError(422, "Tarea padre no válida")

    def create(self, owner: str, data: TaskIn, *, origin: str, actor: str, idem_key: str | None = None) -> dict:
        """-> {task, action, event_id, duplicate}. An equal open task (title + date) is returned instead of duplicated."""
        sources, src_priv = self.resolve_sources(owner, data.sources)
        self._check_parent(owner, data.parent_id)
        _valid_date(data.due_date)
        n = normalize(data.title)

        def dedupe():
            rows = self.con.execute(f"SELECT * FROM tasks WHERE owner=? AND status IN {OPEN} AND due_date IS ?", (owner, data.due_date))
            rule = data.recurrence.model_dump() if data.recurrence else None
            return next((r for r in rows if normalize(r["title"]) == n and json.loads(r["recurrence_json"] or "null") == rule), None)
        privacy = Privacy.strictest(data.privacy, src_priv).value

        def do(action_id):
            if hit := dedupe():  # re-checked under the lock: a concurrent create may have committed meanwhile
                raise _Duplicate(hit)
            tid, now = uuid.uuid4().hex, _utc()
            pos = (self.con.execute("SELECT MAX(position) FROM tasks WHERE owner=?", (owner,)).fetchone()[0] or 0) + 1
            self.con.execute(
                "INSERT INTO tasks (task_id,owner,title,description,status,priority,kind,due_date,due_time,timezone,origin,privacy,project,parent_id,position,sources_json,action_id,created_at,updated_at,completed_at,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, owner, data.title, data.description, data.status, data.priority, data.kind, data.due_date, data.due_time,
                 self.tz, origin, privacy, data.project, data.parent_id, pos, json.dumps(sources, ensure_ascii=False),
                 action_id, now, now, None, 1))
            if data.recurrence:
                attach(self.con, self._row(tid), data.recurrence.model_dump())
            after = self._row(tid)
            ev = self._event(owner, tid, action_id, actor, origin, "create", None, after)
            return tid, ev

        verb = "Borrador creado" if data.status == "draft" else "Tarea creada"
        action, ev, mode = self._run(owner, "task.create", origin, f"{verb}: {data.title}",
                                     data.model_dump(mode="json"), idem_key, do, dedupe)
        if mode == "dup":
            return {"task": self.get(owner, action["task_id"]), "action": None, "event_id": None, "duplicate": True}
        if mode == "replay":
            if action["status"] != "done":
                raise TaskError(409, f"Ese intento ya quedó registrado como «{action['status']}»; no se repite automáticamente")
            t = self.con.execute("SELECT * FROM tasks WHERE task_id=? AND owner=?", (action["task_id"], owner)).fetchone()
            return {"task": _task(t), "action": _action(action), "event_id": None, "duplicate": True}
        return {"task": self.get(owner, action["task_id"]), "action": action, "event_id": ev, "duplicate": False}

    def update(self, owner: str, task_id: str, patch: TaskPatch, *, origin: str, actor: str) -> dict:
        cur = self.get(owner, task_id)
        if cur["version"] != patch.version:
            raise TaskError(409, "La tarea cambió desde que la cargaste; recarga")
        changes = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if k != "version"}
        if not changes:
            raise TaskError(422, "Nada que cambiar")
        _valid_date(changes.get("due_date"))
        if "parent_id" in changes:
            self._check_parent(owner, changes["parent_id"], task_id)

        def do(action_id):
            before = self._row(task_id)
            if before["version"] != patch.version:  # re-check inside the write lock
                raise TaskError(409, "La tarea cambió desde que la cargaste; recarga")
            ch = dict(changes)
            rule = ch.pop("recurrence", None)
            if before["series_id"] and "recurrence" in changes:
                raise TaskError(409, "La regla de una serie es inmutable; detén la serie y crea otra")
            if before["series_id"] and before["status"] in ('done', 'cancelled') and ch.get("status") in OPEN:
                if not self.series(owner, before["series_id"])["active"]:
                    raise TaskError(409, "La serie está detenida")
            if any(ch.get(k, before[k]) is None for k in ("title", "description", "status", "priority", "kind")):
                raise TaskError(422, "Campo obligatorio no puede ser null")
            if ch.get("status") == "done" and before["status"] != "done":
                ch["completed_at"] = _utc()
            elif "status" in ch and ch["status"] != "done":
                ch["completed_at"] = None
            sets = "".join(f"{k}=?, " for k in ch)
            self.con.execute(f"UPDATE tasks SET {sets}updated_at=?, version=version+1 WHERE task_id=? AND owner=?",
                             [*ch.values(), _utc(), task_id, owner])
            if rule:
                attach(self.con, self._row(task_id), rule)
            ev = self._event(owner, task_id, action_id, actor, origin, "update", before, self._row(task_id))
            if before["series_id"] and ch.get("status") in ('done', 'cancelled'):
                series = self.con.execute("SELECT * FROM task_series WHERE series_id=? AND owner=?", (before["series_id"], owner)).fetchone()
                following = next_date(before["occurrence_date"], series["start_date"], json.loads(series["recurrence_json"]))
                if following:
                    materialize(self.con, series, following)
            return task_id, ev

        verb = "Tarea completada" if changes.get("status") == "done" else "Tarea actualizada"
        action, ev, _ = self._run(owner, "task.update", origin, f"{verb}: {cur['title']}", {"task_id": task_id, **changes}, None, do)
        task = self.get(owner, task_id)
        following = None
        if task["series_id"] and task["next_due"]:
            row = self.con.execute("SELECT task_id FROM tasks WHERE owner=? AND series_id=? AND occurrence_date=?", (owner, task["series_id"], task["next_due"]["due_date"])).fetchone()
            following = self.get(owner, row[0]) if row else None
        return {"task": task, "action": action, "event_id": ev, "next": following}

    def reorder(self, owner: str, ids: list[str], *, origin: str, actor: str) -> dict:
        if len(set(ids)) != len(ids) or not ids:
            raise TaskError(422, "Lista de tareas inválida")
        rows = self.con.execute(f"SELECT task_id, position FROM tasks WHERE owner=? AND task_id IN ({','.join('?' * len(ids))})",
                                [owner, *ids]).fetchall()
        if len(rows) != len(ids):
            raise TaskError(404, "Alguna tarea no existe")
        slots = sorted(r["position"] for r in rows)  # reuse the same slots so unrelated tasks keep their place

        def do(action_id):
            first = None
            for tid, pos in zip(ids, slots):
                before = self._row(tid)
                if before["position"] == pos:
                    continue
                self.con.execute("UPDATE tasks SET position=?, updated_at=?, version=version+1 WHERE task_id=?", (pos, _utc(), tid))
                ev = self._event(owner, tid, action_id, actor, origin, "reorder", before, self._row(tid))
                first = first or ev
            return None, first

        action, ev, _ = self._run(owner, "task.reorder", origin, f"Reordenadas {len(ids)} tareas", {"ids": ids}, None, do)
        return {"ok": True, "action": action, "event_id": ev}

    def undo(self, owner: str, event_id: int, *, actor: str) -> dict:
        ev = self.con.execute("SELECT * FROM task_events WHERE event_id=? AND owner=?", (event_id, owner)).fetchone()
        if not ev:
            raise TaskError(404, "Cambio no encontrado")
        if ev["undone_at"] or ev["op"] == "undo":
            raise TaskError(409, "Ese cambio ya no se puede deshacer")
        group = self.con.execute("SELECT * FROM task_events WHERE owner=? AND action_id IS ? AND undone_at IS NULL AND op != 'undo' "
                                 "ORDER BY event_id DESC", (owner, ev["action_id"])).fetchall() if ev["action_id"] else [ev]

        def do(action_id):
            for g in group:
                after = json.loads(g["after_json"])
                cur = self._row(g["task_id"])
                if g["op"] in ("series_stop", "occurrence") or (cur["series_id"] and (g["op"] == "create" or not (json.loads(g["before_json"] or '{}').get('series_id')))):
                    raise TaskError(409, "No se deshace el alta o la detención de una serie; usa detener serie")
                if cur["version"] != after["version"]:
                    raise TaskError(409, f"«{cur['title']}» cambió después; no se puede deshacer sin perder ese cambio")
                before = json.loads(g["before_json"]) if g["before_json"] else None
                # Undoing a create cancels the task (kept for the audit trail) instead of deleting it.
                restore = {k: before[k] for k in (*TASK_FIELDS, "position", "completed_at")} if before else {"status": "cancelled"}
                sets = ", ".join(f"{k}=?" for k in restore)
                self.con.execute(f"UPDATE tasks SET {sets}, updated_at=?, version=version+1 WHERE task_id=?",
                                 [*restore.values(), _utc(), g["task_id"]])
                self.con.execute("UPDATE task_events SET undone_at=? WHERE event_id=?", (_utc(), g["event_id"]))
                self._event(owner, g["task_id"], action_id, actor, "user", "undo", cur, self._row(g["task_id"]))
            return group[0]["task_id"], None

        action, _, _ = self._run(owner, "task.undo", "user", f"Deshecho el cambio {event_id}", {"event_id": event_id}, None, do)
        return {"task": self.get(owner, group[0]["task_id"]), "action": action}

    # ------------------------------------------------------------------ recovery
    def reconcile(self) -> int:
        """After a crash: a `running` action either committed its change (done) or did not (failed). Never re-run."""
        n = 0
        for a in self.con.execute("SELECT action_id FROM actions WHERE status='running'").fetchall():
            applied = self.con.execute("SELECT 1 FROM task_events WHERE action_id=? LIMIT 1", (a["action_id"],)).fetchone()
            with tx(self.con):
                self.con.execute(
                    "UPDATE actions SET status=?, error=?, updated_at=? WHERE action_id=? AND status='running'",
                    ("done", None, _utc(), a["action_id"]) if applied else
                    ("failed", "Interrumpida antes de aplicarse (verificado: sin cambios). No se reintenta sola.", _utc(), a["action_id"]))
            n += 1
        return n


def _valid_date(d: str | None) -> None:
    if d is None:
        return
    try:
        date.fromisoformat(d)
    except ValueError as e:
        raise TaskError(422, "Fecha inválida") from e
