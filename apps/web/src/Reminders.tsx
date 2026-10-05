import { useCallback, useEffect, useRef, useState } from "react";
import { api, errMsg } from "./api";

type Reminder = { reminder_id: number; task_id: string; title: string; scheduled_at: string; timezone: string; read_at: string | null };
type Inbox = { enabled: boolean; unread: number; items: Reminder[] };

export function Reminders() {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
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
    return () => window.clearInterval(timer);
  }, [load]);

  async function acknowledge(id: number) {
    setBusy(id);
    try { await api(`/api/reminders/${id}/ack`, "POST"); await load(); }
    catch (e) { setError(errMsg(e)); }
    finally { setBusy(null); }
  }
  if (inbox && !inbox.enabled) return null;
  const pending = inbox?.items.filter((item) => !item.read_at) ?? [];
  return (
    <div className="reminder-menu">
      <button className="ghost small" aria-expanded={open} aria-controls="reminder-panel" onClick={() => { setOpen(!open); void load(); }}>
        Recordatorios {inbox && inbox.unread > 0 && <span className="reminder-badge">{inbox.unread}</span>}
      </button>
      <span className="sr-only" role="status" aria-live="polite">{inbox?.unread ? `${inbox.unread} recordatorios pendientes` : "Sin recordatorios pendientes"}</span>
      {open && <section id="reminder-panel" className="reminder-panel card" aria-labelledby="reminder-title">
        <div className="row"><h2 id="reminder-title">Tus recordatorios</h2><button className="ghost small" onClick={() => setOpen(false)}>Cerrar</button></div>
        {error && <p className="error" role="alert">{error}</p>}
        {!inbox && !error && <p className="muted">Cargando…</p>}
        {inbox && pending.length === 0 && <p className="muted">No hay avisos pendientes.</p>}
        <ul className="reminder-list">{pending.map((item) => <li key={item.reminder_id}>
          <strong>{item.title}</strong>
          <p className="muted small-text">{new Intl.DateTimeFormat("es-CL", { dateStyle: "short", timeStyle: "short", timeZone: item.timezone }).format(new Date(item.scheduled_at))}</p>
          <div className="row"><a href="#today" onClick={() => setOpen(false)}>Ver agenda</a>
            <button className="ghost small" disabled={busy !== null} onClick={() => void acknowledge(item.reminder_id)}>{busy === item.reminder_id ? "Guardando…" : "Marcar leído"}</button></div>
        </li>)}</ul>
        <p className="muted small-text">Los avisos se guardan aunque cierres el navegador. Puedes revisarlos al volver a Alice.</p>
      </section>}
    </div>
  );
}
