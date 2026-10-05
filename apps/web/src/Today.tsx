import { useCallback, useEffect, useRef, useState } from "react";
import { api, errMsg, fmtTime, raw, HttpError } from "./api";
import { PageHead } from "./pages";
import { Orb, type Tint } from "./Orb";
import { PrivBadge } from "./Chat";
import { ACTION_STATUS_LABEL, KIND_LABEL, PRIORITY_LABEL, type Action, type Kind, type Priority, type Task } from "./tasks";

type Recommendation = { task_id: string; title: string; reason: string; rank: number };
type TodayResp = {
  date: string; timezone: string; overdue: Task[]; today: Task[]; upcoming: Task[]; undated: Task[]; drafts: Task[];
  recommendations: Recommendation[]; recent_actions: Action[];
};
type CreatePayload = { title: string; due_date: string | null; due_time: string | null; priority: Priority; kind: Kind };
type EditPayload = Partial<Pick<Task, "title" | "description" | "due_date" | "due_time" | "priority" | "status">>;
type Notice = { msg: string; eventId: number | null };

const fmtDue = (date: string, time: string | null) => {
  const s = new Date(date + "T00:00:00").toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
  return time ? `${s} · ${time}` : s;
};

export function Today() {
  const [data, setData] = useState<TodayResp | null>(null);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const noticeTimer = useRef<number | null>(null);

  const load = useCallback(() => api<TodayResp>("/api/today").then((d) => { setData(d); setErr(""); }).catch((e) => setErr(errMsg(e))), []);
  useEffect(() => { load(); const timer = window.setInterval(load, 15_000); return () => window.clearInterval(timer); }, [load]);
  useEffect(() => () => { if (noticeTimer.current) window.clearTimeout(noticeTimer.current); }, []);

  function notify(msg: string, eventId: number | null) {
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    setNotice({ msg, eventId });
    noticeTimer.current = window.setTimeout(() => setNotice(null), 10000);
  }

  function withBusy<T>(id: string, fn: () => Promise<T>): Promise<T> {
    setBusyIds((s) => new Set(s).add(id));
    return fn().finally(() => setBusyIds((s) => { const n = new Set(s); n.delete(id); return n; }));
  }

  async function undo(eventId: number) {
    try {
      await api(`/api/events/${eventId}/undo`, "POST");
      setNotice(null);
    } catch (e) {
      setErr(e instanceof HttpError && e.status === 409 ? "Ya no se puede deshacer: la tarea cambió después." : errMsg(e));
    }
    await load();
  }

  async function patchTask(t: Task, changes: EditPayload, msg: string) {
    setErr("");
    try {
      const r = await withBusy(t.task_id, () => api<{ task: Task; event_id: number }>(`/api/tasks/${t.task_id}`, "PATCH", { version: t.version, ...changes }));
      await load();
      notify(msg, r.event_id);
    } catch (e) {
      if (e instanceof HttpError && e.status === 409) setErr("Alguien más cambió esta tarea; se recargó.");
      else setErr(errMsg(e));
      await load();
    }
  }

  async function reorder(ids: string[], i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    const next = ids.slice();
    [next[i], next[j]] = [next[j], next[i]];
    setErr("");
    try {
      const r = await withBusy(ids[i], () => api<{ ok: boolean; event_id: number | null }>("/api/tasks/reorder", "POST", { ids: next }));
      await load();
      notify("Hecho · orden actualizado", r.event_id);
    } catch (e) { setErr(errMsg(e)); }
  }

  async function createTask(p: CreatePayload) {
    setErr(""); setCreating(true);
    try {
      const key = crypto.randomUUID();
      const r = await raw("/api/tasks", {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({ title: p.title, due_date: p.due_date ?? undefined, due_time: p.due_time ?? undefined, priority: p.priority, kind: p.kind }),
      });
      const body = await r.json() as { task: Task; action: Action; event_id: number; duplicate: boolean };
      await load();
      notify(body.duplicate ? "Ya existía una tarea igual" : `Hecho · tarea creada: ${body.task.title}`, body.duplicate ? null : body.event_id);
    } catch (e) { setErr(errMsg(e)); }
    setCreating(false);
  }

  const disabledIds = busyIds;
  const toggleDone = (t: Task, done: boolean) =>
    patchTask(t, { status: done ? "done" : "open" }, done ? `Hecho · «${t.title}» completada` : `Hecho · «${t.title}» reabierta`);
  const saveEdits = (t: Task, ch: EditPayload) => patchTask(t, ch, `Hecho · «${ch.title ?? t.title}» actualizada`);
  const activate = (t: Task) => patchTask(t, { status: "open" }, `Hecho · «${t.title}» activada`);

  return (
    <section className="page">
      <PageHead title="Hoy" sub={data ? `${data.date} · zona horaria ${data.timezone}` : "Cargando tus tareas…"}>
        <button className="ghost small" onClick={load}>Actualizar</button>
      </PageHead>

      {notice && (
        <div className="notice" role="status" aria-live="polite">
          <span>{notice.msg}</span>
          <div className="row">
            {notice.eventId != null && <button className="ghost small" onClick={() => undo(notice.eventId!)}>Deshacer</button>}
            <button className="ghost small" onClick={() => setNotice(null)} aria-label="Cerrar aviso">Cerrar</button>
          </div>
        </div>
      )}
      {err && <p className="error" role="alert">{err}</p>}
      {data && <ReminderOrb data={data} />}

      <div className="card">
        <h2>Crear tarea</h2>
        <QuickCreateForm onCreate={createTask} busy={creating} />
        <p className="muted small-text">Añade fecha y hora para recibir un recordatorio en Alice. Una fecha sin hora queda en tu agenda.</p>
      </div>

      {!data ? !err && <p className="muted">Cargando…</p> : <>
        <Section title="Vencidas" tasks={data.overdue} emptyText="Sin tareas vencidas." disabledIds={disabledIds}
          onToggleDone={toggleDone} onSave={saveEdits} onActivate={activate} onReorder={reorder} />
        <Section title="Hoy" tasks={data.today} emptyText="Nada programado para hoy." disabledIds={disabledIds}
          onToggleDone={toggleDone} onSave={saveEdits} onActivate={activate} onReorder={reorder} />
        <Section title="Próximas" tasks={data.upcoming} emptyText="Sin tareas en los próximos 7 días." disabledIds={disabledIds}
          onToggleDone={toggleDone} onSave={saveEdits} onActivate={activate} onReorder={reorder} />
        <Section title="Sin fecha" tasks={data.undated} emptyText="Sin tareas sin fecha." disabledIds={disabledIds}
          onToggleDone={toggleDone} onSave={saveEdits} onActivate={activate} onReorder={reorder} />
        <Section title="Borradores" tasks={data.drafts} emptyText="Sin borradores." disabledIds={disabledIds}
          onToggleDone={toggleDone} onSave={saveEdits} onActivate={activate} onReorder={reorder} />

        <div className="card">
          <h2>Recomendaciones</h2>
          <p className="muted small-text">Sugerencias de Alice a partir de tus tareas y datos; no se ha ejecutado nada.</p>
          {data.recommendations.length === 0 ? <p className="muted">Sin sugerencias por ahora.</p> : (
            <ul className="reco-list">
              {[...data.recommendations].sort((a, b) => a.rank - b.rank).map((r) => (
                <li key={r.task_id}><strong>{r.title}</strong><p className="muted small-text">{r.reason}</p></li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <h2>Registro de acciones</h2>
          {data.recent_actions.length === 0 ? <p className="muted">Sin acciones recientes.</p> : (
            <ul className="action-log">
              {data.recent_actions.map((a) => (
                <li key={a.action_id} className={`action-${a.status}`}>
                  <strong>{ACTION_STATUS_LABEL[a.status]}</strong> — {a.summary}
                  {a.status === "failed" && a.error && <p className="error small-text">{a.error}</p>}
                  <p className="muted small-text">{fmtTime(a.updated_at)}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </>}
    </section>
  );
}

function QuickCreateForm({ onCreate, busy }: { onCreate: (p: CreatePayload) => void; busy: boolean }) {
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [dueTime, setDueTime] = useState("");
  const [priority, setPriority] = useState<Priority>(3);
  const [kind, setKind] = useState<Kind>("personal");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const t = title.trim();
    if (!t || busy) return;
    onCreate({ title: t, due_date: dueDate || null, due_time: dueDate && dueTime ? dueTime : null, priority, kind });
    setTitle(""); setDueDate(""); setDueTime("");
  }

  return (
    <form className="row wrap" onSubmit={submit}>
      <label className="sr-only" htmlFor="qc-title">Título de la tarea</label>
      <input id="qc-title" className="qc-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Nueva tarea…" required />
      <label className="inline">Fecha <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} /></label>
      <label className="inline">Hora del aviso <input type="time" value={dueTime} disabled={!dueDate} onChange={(e) => setDueTime(e.target.value)} /></label>
      <label className="inline">Prioridad
        <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as Priority)}>
          {([1, 2, 3, 4] as Priority[]).map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
        </select>
      </label>
      <label className="inline">Tipo
        <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
          <option value="personal">Personal</option><option value="work">Trabajo</option>
        </select>
      </label>
      <button className="primary small" disabled={busy || !title.trim()}>{busy ? "Creando…" : "Crear"}</button>
    </form>
  );
}

function Section({ title, tasks, emptyText, disabledIds, onToggleDone, onSave, onActivate, onReorder }: {
  title: string; tasks: Task[]; emptyText: string; disabledIds: Set<string>;
  onToggleDone: (t: Task, done: boolean) => void; onSave: (t: Task, changes: EditPayload) => void; onActivate: (t: Task) => void;
  onReorder: (ids: string[], i: number, dir: -1 | 1) => void;
}) {
  return (
    <div className="card">
      <h2>{title} {tasks.length > 0 && <span className="muted">({tasks.length})</span>}</h2>
      {tasks.length === 0 ? <p className="muted">{emptyText}</p> : (
        <ul className="task-list">
          {tasks.map((t, i) => (
            <TaskRow key={t.task_id} task={t} disabled={disabledIds.has(t.task_id)} canMoveUp={i > 0} canMoveDown={i < tasks.length - 1}
              onToggleDone={onToggleDone} onSave={onSave} onActivate={onActivate}
              onMoveUp={() => onReorder(tasks.map((x) => x.task_id), i, -1)}
              onMoveDown={() => onReorder(tasks.map((x) => x.task_id), i, 1)} />
          ))}
        </ul>
      )}
    </div>
  );
}

function TaskRow({ task, disabled, canMoveUp, canMoveDown, onToggleDone, onSave, onActivate, onMoveUp, onMoveDown }: {
  task: Task; disabled: boolean; canMoveUp: boolean; canMoveDown: boolean;
  onToggleDone: (t: Task, done: boolean) => void; onSave: (t: Task, changes: EditPayload) => void; onActivate: (t: Task) => void;
  onMoveUp: () => void; onMoveDown: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [dueDate, setDueDate] = useState(task.due_date ?? "");
  const [dueTime, setDueTime] = useState(task.due_time ?? "");
  const [priority, setPriority] = useState<Priority>(task.priority);

  function startEdit() {
    setTitle(task.title); setDescription(task.description); setDueDate(task.due_date ?? ""); setPriority(task.priority);
    setDueTime(task.due_time ?? "");
    setEditing(true);
  }
  function save(e: React.FormEvent) {
    e.preventDefault();
    onSave(task, { title: title.trim(), description, due_date: dueDate || null, due_time: dueDate && dueTime ? dueTime : null, priority });
    setEditing(false);
  }

  return (
    <li className="task-row">
      <input type="checkbox" checked={task.status === "done"} disabled={disabled || task.status === "draft" || task.status === "cancelled"}
        onChange={(e) => onToggleDone(task, e.target.checked)}
        aria-label={`Marcar «${task.title}» como ${task.status === "done" ? "pendiente" : "hecha"}`} />
      <div className="task-main">
        {editing ? (
          <form className="task-edit" onSubmit={save}>
            <label className="sr-only" htmlFor={`t-${task.task_id}-title`}>Título</label>
            <input id={`t-${task.task_id}-title`} value={title} onChange={(e) => setTitle(e.target.value)} required />
            <label className="sr-only" htmlFor={`t-${task.task_id}-desc`}>Descripción</label>
            <textarea id={`t-${task.task_id}-desc`} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Descripción (opcional)" />
            <div className="row wrap">
              <label className="inline">Fecha <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} /></label>
              <label className="inline">Hora del aviso <input type="time" value={dueTime} disabled={!dueDate} onChange={(e) => setDueTime(e.target.value)} /></label>
              <label className="inline">Prioridad
                <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as Priority)}>
                  {([1, 2, 3, 4] as Priority[]).map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
                </select>
              </label>
              <button className="primary small" disabled={disabled}>Guardar</button>
              <button type="button" className="ghost small" onClick={() => setEditing(false)}>Cancelar</button>
            </div>
          </form>
        ) : (
          <>
            <span className={`task-title ${task.status === "done" ? "done" : ""}`}>{task.title}</span>
            {task.description && <p className="muted small-text">{task.description}</p>}
            <div className="task-meta">
              <span className="badge">{PRIORITY_LABEL[task.priority]}</span>
              <span className="badge">{KIND_LABEL[task.kind]}</span>
              {task.due_date && <span>{fmtDue(task.due_date, task.due_time)}</span>}
              <PrivBadge p={task.privacy} />
              {task.status === "draft" && <span className="draft-flag">Borrador: aún no es una tarea activa</span>}
            </div>
            {task.sources.length > 0 && (
              <ul className="task-sources">
                {task.sources.map((s, i) => (
                  <li key={i}>{s.kind === "log" ? "Registro" : "Documento"}: {s.title}
                    {s.location ? ` — ${s.location}` : ""}{s.excerpt ? ` · «${s.excerpt}»` : ""}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
      <div className="task-actions">
        <div className="row">
          <button className="ghost small" onClick={onMoveUp} disabled={disabled || !canMoveUp} aria-label={`Subir «${task.title}»`}>▲</button>
          <button className="ghost small" onClick={onMoveDown} disabled={disabled || !canMoveDown} aria-label={`Bajar «${task.title}»`}>▼</button>
        </div>
        <div className="row">
          {task.status === "draft" && <button className="small" onClick={() => onActivate(task)} disabled={disabled}>Activar</button>}
          {!editing && task.status !== "cancelled" && <button className="ghost small" onClick={startEdit} disabled={disabled}>Editar</button>}
        </div>
      </div>
    </li>
  );
}

// Reminders orb: copper while something is overdue, bright cyan when a timed task is due within the hour,
// soft cyan with tasks left today, calm violet on a clear day. The orb eases between states (Orb.tsx).
const SOON_MS = 60 * 60 * 1000;
const isOpen = (t: Task) => t.status !== "done" && t.status !== "cancelled";

function ReminderOrb({ data }: { data: TodayResp }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 60_000); return () => window.clearInterval(t); }, []);
  const overdue = [...data.overdue, ...data.today.filter((t) => t.due_at && Date.parse(t.due_at) <= now)].filter(isOpen);
  const today = data.today.filter(isOpen);
  const soon = [...today, ...data.upcoming.filter(isOpen)].filter((t) => {
    if (!t.due_date || !t.due_time) return false;
    const ms = t.due_at ? Date.parse(t.due_at) - now : Number.NaN;
    return ms > 0 && ms <= SOON_MS;
  });
  const [tint, energy, count, title, detail]: [Tint, number, number, string, string] =
    overdue.length ? ["copper", 0.6, overdue.length, overdue.length === 1 ? "1 tarea vencida" : `${overdue.length} tareas vencidas`, `La más antigua: «${overdue[0].title}».`]
    : soon.length ? ["cyan", 0.85, soon.length, "Vence pronto", `«${soon[0].title}» a las ${soon[0].due_time!.slice(0, 5)}.`]
    : today.length ? ["cyan", 0.35, today.length, today.length === 1 ? "1 tarea para hoy" : `${today.length} tareas para hoy`, "Nada vence en la próxima hora."]
    : ["violet", 0.12, 0, "Día despejado", "No hay recordatorios pendientes."];

  return (
    <div className="card reminders" role="status" aria-live="polite">
      <Orb size={132} tint={tint} energy={energy}>
        <span className="reminders-count" aria-hidden="true">{count}</span>
      </Orb>
      <div>
        <h2>{title}</h2>
        <p className="muted">{detail}</p>
      </div>
    </div>
  );
}
