import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, errMsg, HttpError } from "./api";
import type { Inbox, Reminder } from "./tasks";

export const fmtAt = (iso: string, timeZone?: string) =>
  new Intl.DateTimeFormat("es-CL", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone }).format(new Date(iso));
export const taskLink = (taskId: string, reminderId?: number) =>
  `#today?task=${encodeURIComponent(taskId)}${reminderId != null ? `&reminder=${reminderId}` : ""}`;

export async function snoozeReminder(id: number, how: { minutes: number } | { until: string }): Promise<Reminder> {
  try { return await api<Reminder>(`/api/reminders/${id}/snooze`, "POST", how); }
  catch (e) {
    if (e instanceof HttpError && e.status === 409) throw new Error("La tarea ya cambió (completada o reprogramada); no se pospuso.");
    if (e instanceof HttpError && e.status === 422) throw new Error("Elige una hora futura.");
    if (e instanceof HttpError && e.status === 404) throw new Error("Este aviso ya no existe.");
    throw e;
  }
}

// datetime-local value for "now + m minutes" in the browser's zone (the input has no zone of its own).
const localInput = (m: number) => {
  const d = new Date(Date.now() + m * 60_000);
  d.setSeconds(0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
};

// Snooze: two one-tap choices plus "Otra hora" (one more step, so the row stays short).
export function SnoozeControls({ reminder, onDone, compact = false }: {
  reminder: Reminder; onDone: (msg: string) => void; compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [custom, setCustom] = useState(false);
  const [when, setWhen] = useState(() => localInput(180));
  const [err, setErr] = useState("");
  const id = useId();

  async function run(how: { minutes: number } | { until: string }) {
    setBusy(true); setErr("");
    try {
      const r = await snoozeReminder(reminder.reminder_id, how);
      setCustom(false);
      onDone(`Pospuesto · te aviso ${fmtAt(r.snoozed_until ?? r.scheduled_at, r.timezone)}`);
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className={`snooze${compact ? " is-compact" : ""}`} role="group" aria-label={`Posponer «${reminder.title}»`}>
      <button type="button" className="small" disabled={busy} onClick={() => run({ minutes: 10 })}>10 min</button>
      <button type="button" className="small" disabled={busy} onClick={() => run({ minutes: 60 })}>1 hora</button>
      {!custom ? (
        <button type="button" className="ghost small" disabled={busy} aria-expanded={false} onClick={() => setCustom(true)}>Otra hora…</button>
      ) : (
        <form className="snooze-custom" onSubmit={(e) => { e.preventDefault(); if (when) run({ until: new Date(when).toISOString() }); }}>
          <label htmlFor={id} className="sr-only">Avisarme el</label>
          <input id={id} type="datetime-local" value={when} min={localInput(1)} onChange={(e) => setWhen(e.target.value)} required autoFocus />
          <button className="primary small" disabled={busy || !when}>Posponer</button>
          <button type="button" className="ghost small" onClick={() => setCustom(false)}>Cancelar</button>
        </form>
      )}
      {err && <p className="error small-text" role="alert">{err}</p>}
    </div>
  );
}

export const pendingOf = (inbox: Inbox | null) =>
  inbox?.items.filter((r) => !r.read_at && !(r.snoozed_until && Date.parse(r.snoozed_until) > Date.now())) ?? [];

export function Reminders() {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const lastUnread = useRef<number | null>(null);
  const load = useCallback(async () => {
    try {
      const next = await api<Inbox>("/api/reminders");
      if (lastUnread.current !== null && next.unread > lastUnread.current) setOpen(true);
      lastUnread.current = next.unread;
      setInbox(next); setError("");
    }
    catch (e) { setError(errMsg(e)); }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    window.addEventListener("alice-reminders-changed", load);
    return () => { window.clearInterval(timer); window.removeEventListener("alice-reminders-changed", load); };
  }, [load]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);

  async function acknowledge(id: number) {
    setBusy(id);
    try { await api(`/api/reminders/${id}/ack`, "POST"); await load(); }
    catch (e) { setError(errMsg(e)); }
    finally { setBusy(null); }
  }
  if (inbox && !inbox.enabled) return null;
  const pending = pendingOf(inbox);
  const changed = (msg: string) => { setNote(msg); void load(); window.dispatchEvent(new Event("alice-reminders-changed")); };
  return (
    <div className="reminder-menu">
      <button className="ghost small" aria-expanded={open} aria-controls="reminder-panel" onClick={() => { setOpen(!open); void load(); }}>
        Avisos {pending.length > 0 && <span className="reminder-badge">{pending.length}</span>}
      </button>
      <span className="sr-only" role="status" aria-live="polite">{pending.length ? `${pending.length} avisos pendientes` : "Sin avisos pendientes"}</span>
      {open && <section id="reminder-panel" className="reminder-panel card" aria-labelledby="reminder-title">
        <div className="row"><h2 id="reminder-title">Avisos</h2><button className="ghost small" onClick={() => setOpen(false)}>Cerrar</button></div>
        {error && <p className="error" role="alert">{error}</p>}
        {note && <p className="ok-text small-text" role="status">{note}</p>}
        {!inbox && !error && <p className="muted">Cargando…</p>}
        {inbox && pending.length === 0 && <p className="muted">Nada pendiente. Te aviso cuando toque.</p>}
        <ul className="reminder-list">{pending.map((item) => <li key={item.reminder_id}>
          <strong>{item.title}</strong>
          <p className="muted small-text">{fmtAt(item.scheduled_at, item.timezone)}</p>
          <SnoozeControls reminder={item} onDone={changed} compact />
          <div className="row">
            <a className="button small" href={taskLink(item.task_id, item.reminder_id)} onClick={() => setOpen(false)}>Ver tarea</a>
            <button className="ghost small" disabled={busy !== null} onClick={() => void acknowledge(item.reminder_id)}>{busy === item.reminder_id ? "Guardando…" : "Marcar leído"}</button>
          </div>
        </li>)}</ul>
      </section>}
    </div>
  );
}
