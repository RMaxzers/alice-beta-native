import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api, errMsg, fmtTime, raw, HttpError } from "./api";
import { PageHead } from "./pages";
import { Orb, type Tint } from "./Orb";
import { PrivBadge } from "./Chat";
import { DevicePush } from "./DevicePush";
import { SnoozeControls, pendingOf, snoozeReminder } from "./Reminders";
import type { Focus } from "./main";
import {
  ACTION_STATUS_LABEL, FREQ_LABEL, KIND_LABEL, PRIORITY_LABEL, WEEKDAYS, describeRecurrence, fmtWhen, isoWeekday,
  type Action, type DailySummary, type Freq, type Inbox, type Kind, type Priority, type Recurrence, type Reminder, type Task, type Weekday,
} from "./tasks";

type Recommendation = { task_id: string; title: string; reason: string; rank: number };
type TodayResp = {
  date: string; timezone: string; overdue: Task[]; today: Task[]; upcoming: Task[]; undated: Task[]; drafts: Task[];
  recommendations: Recommendation[]; recent_actions: Action[];
};
type Fields = { title: string; description: string; due_date: string | null; due_time: string | null; priority: Priority; kind: Kind; recurrence: Recurrence | null };
type EditPayload = Partial<Pick<Task, "title" | "description" | "due_date" | "due_time" | "priority" | "status" | "recurrence">>;
type PatchResp = { task: Task; event_id: number; next?: Task | null };
type Notice = { msg: string; eventId: number | null };

const isOpen = (t: Task) => t.status !== "done" && t.status !== "cancelled";
// The worker materializes a week of each series; future lists show only its next occurrence (+N later).
type Shown = Task & { later?: number };
function firstOfSeries(ts: Task[]): Shown[] {
  const seen = new Map<string, Shown>();
  const out: Shown[] = [];
  for (const t of ts) {
    const k = t.series_id;
    if (!k) { out.push(t); continue; }
    const first = seen.get(k);
    if (first) { first.later = (first.later ?? 0) + 1; continue; }
    const c: Shown = { ...t, later: 0 }; seen.set(k, c); out.push(c);
  }
  return out;
}
const SOON_MS = 60 * 60 * 1000;

// Older backends have no /api/summary/daily: derive the same shape from /api/today so the page still works.
function deriveSummary(d: TodayResp): DailySummary {
  const today = d.today.filter(isOpen), overdue = d.overdue.filter(isOpen), upcoming = d.upcoming.filter(isOpen);
  return { date: d.date, timezone: d.timezone, counts: { pending: today.length, overdue: overdue.length, upcoming: upcoming.length },
    next: overdue[0] ?? today[0] ?? null, overdue: overdue.slice(0, 5), today: today.slice(0, 5), upcoming: upcoming.slice(0, 5) };
}

export function Today({ focus, onFocusHandled }: { focus?: Focus | null; onFocusHandled?: () => void }) {
  const [data, setData] = useState<TodayResp | null>(null);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [highlight, setHighlight] = useState<string | null>(null);
  // After a completion the next item can land under the pointer: a short pause stops double-click cascades.
  const [cooling, setCooling] = useState(false);
  const noticeTimer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [d, s, r] = await Promise.all([
        api<TodayResp>("/api/today"),
        api<DailySummary>("/api/summary/daily").catch((e) => (e instanceof HttpError && e.status === 404 ? null : Promise.reject(e))),
        api<Inbox>("/api/reminders").catch(() => null),
      ]);
      setData(d); setSummary(s ?? deriveSummary(d)); setInbox(r); setErr("");
    } catch (e) { setErr(errMsg(e)); }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 15_000);
    window.addEventListener("alice-reminders-changed", load);
    return () => { window.clearInterval(timer); window.removeEventListener("alice-reminders-changed", load); };
  }, [load]);
  useEffect(() => () => { if (noticeTimer.current) window.clearTimeout(noticeTimer.current); }, []);

  function notify(msg: string, eventId: number | null = null) {
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    setNotice({ msg, eventId });
    noticeTimer.current = window.setTimeout(() => setNotice(null), 12000);
  }
  const remindersChanged = (msg: string) => { notify(msg); void load(); window.dispatchEvent(new Event("alice-reminders-changed")); };

  const all = data ? [...data.overdue, ...data.today, ...data.upcoming, ...data.undated, ...data.drafts] : [];
  const findTask = (id: string) => all.find((t) => t.task_id === id) ?? null;

  // Deep link (notification / "Ver tarea"): optionally snooze, then scroll to the task and focus it.
  useEffect(() => {
    if (!focus || !data) return;
    onFocusHandled?.();
    history.replaceState(null, "", "#today"); // a reload must not repeat ?snooze=
    (async () => {
      if (focus.snooze && focus.reminder != null) {
        try { const r = await snoozeReminder(focus.reminder, { minutes: focus.snooze }); remindersChanged(`Pospuesto ${focus.snooze} min · «${r.title}»`); }
        catch (e) { setErr(errMsg(e)); }
      }
      const t = findTask(focus.task);
      if (!t) {
        const gone = await api<{ task?: Task } & Partial<Task>>(`/api/tasks/${encodeURIComponent(focus.task)}`).catch(() => null);
        const g = gone?.task ?? (gone as Task | null);
        notify(g?.title ? `«${g.title}» ya está ${g.status === "done" ? "completada" : g.status === "cancelled" ? "cancelada" : "fuera de esta vista"}.` : "No encontré esa tarea.");
        return;
      }
      setHighlight(t.task_id);
      requestAnimationFrame(() => {
        const el = document.getElementById(`task-${t.task_id}`);
        el?.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        el?.focus({ preventScroll: true });
      });
      window.setTimeout(() => setHighlight(null), 6000);
    })();
  }, [focus?.at, data != null]); // eslint-disable-line react-hooks/exhaustive-deps

  function withBusy<T>(id: string, fn: () => Promise<T>): Promise<T> {
    setBusyIds((s) => new Set(s).add(id));
    return fn().finally(() => setBusyIds((s) => { const n = new Set(s); n.delete(id); return n; }));
  }

  async function undo(eventId: number) {
    try { await api(`/api/events/${eventId}/undo`, "POST"); setNotice(null); }
    catch (e) { setErr(e instanceof HttpError && e.status === 409 ? "Ya no se puede deshacer: la tarea cambió después." : errMsg(e)); }
    await load();
  }

  async function patchTask(t: Task, changes: EditPayload, msg: (r: PatchResp) => string) {
    setErr("");
    try {
      const r = await withBusy(t.task_id, () => api<PatchResp>(`/api/tasks/${t.task_id}`, "PATCH", { version: t.version, ...changes }));
      await load();
      notify(msg(r), r.event_id);
      window.dispatchEvent(new Event("alice-reminders-changed"));
    } catch (e) {
      if (e instanceof HttpError && e.status === 409) setErr("Esta tarea cambió en otro lugar; la recargué.");
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
      notify("Orden actualizado", r.event_id);
    } catch (e) { setErr(errMsg(e)); }
  }

  async function createTask(p: Fields): Promise<boolean> {
    setErr(""); setCreating(true);
    try {
      const r = await raw("/api/tasks", {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ title: p.title, description: p.description || undefined, due_date: p.due_date ?? undefined, due_time: p.due_time ?? undefined,
          priority: p.priority, kind: p.kind, recurrence: p.recurrence ?? undefined }),
      });
      const body = await r.json() as { task: Task; event_id: number; duplicate: boolean };
      await load();
      const rec = body.task.recurrence ?? p.recurrence;
      notify(body.duplicate ? "Ya existía una tarea igual." : `Creada: ${body.task.title}${rec ? ` · ${describeRecurrence(rec, body.task.due_date)}` : ""}`,
        body.duplicate || rec ? null : body.event_id); // undo of a new series is refused (409): stop the series instead
      return true;
    } catch (e) { setErr(errMsg(e)); return false; }
    finally { setCreating(false); }
  }

  const completeMsg = (t: Task) => (r: PatchResp) => {
    if (!t.recurrence) return `Hecha: «${t.title}»`;
    const next = r.next ?? null;
    return next ? `Hecha esta vez. La siguiente: ${fmtWhen(next)}` : r.next === null ? `Hecha. Era la última de la serie.` : `Hecha esta vez. La serie sigue.`;
  };
  const toggleDone = (t: Task, done: boolean) => {
    if (cooling) return;
    setCooling(true); window.setTimeout(() => setCooling(false), 800);
    return patchTask(t, { status: done ? "done" : "open" }, done ? completeMsg(t) : () => `Reabierta: «${t.title}»`);
  };
  const saveEdits = (t: Task, ch: EditPayload) => patchTask(t, ch, () => `Guardada: «${ch.title ?? t.title}»`);
  const activate = (t: Task) => patchTask(t, { status: "open" }, () => `Activada: «${t.title}»`);

  const pending = pendingOf(inbox);
  const blocked = cooling ? new Set(all.map((t) => t.task_id)) : busyIds;
  const rows = { today: data?.date ?? "", disabledIds: blocked, highlight, reminders: inbox?.items ?? [], onToggleDone: toggleDone, onSave: saveEdits, onActivate: activate, onReorder: reorder, onSnoozed: remindersChanged, onStopped: remindersChanged };

  return (
    <section className="page today">
      <PageHead title="Hoy" sub={data ? `${new Date(data.date + "T00:00:00").toLocaleDateString("es-CL", { weekday: "long", day: "numeric", month: "long" })}` : "Cargando…"}>
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

      {data && summary && <DayCard summary={summary} data={data} pending={pending} findTask={findTask}
        snoozed={(inbox?.items ?? []).filter((r) => r.snoozed_until)} // snooze also sets read_at (contract v2)
        busy={blocked} onDone={(t) => toggleDone(t, true)} onSnoozed={remindersChanged} />}

      <QuickCreate onCreate={createTask} busy={creating} />

      {!data ? !err && <p className="muted">Cargando…</p> : <>
        <Section id="sec-overdue" title="Vencidas" tasks={data.overdue} emptyText="Nada vencido." {...rows} />
        <Section id="sec-today" title="Hoy" tasks={data.today} emptyText="Nada más para hoy." {...rows} />
        <Section id="sec-upcoming" title="Próximas" tasks={firstOfSeries(data.upcoming)} emptyText="Nada en los próximos 7 días." {...rows} />
        <Section id="sec-undated" title="Sin fecha" tasks={data.undated} emptyText="Sin tareas sin fecha." collapsible {...rows} />
        <Section id="sec-drafts" title="Borradores" tasks={data.drafts} emptyText="Sin borradores." collapsible {...rows} />

        <details className="card fold">
          <summary><h2>Sugerencias de Alice {data.recommendations.length > 0 && <span className="muted">({data.recommendations.length})</span>}</h2></summary>
          <p className="muted small-text">Solo sugerencias; no se ha ejecutado nada.</p>
          {data.recommendations.length === 0 ? <p className="muted">Sin sugerencias por ahora.</p> : (
            <ul className="reco-list">
              {[...data.recommendations].sort((a, b) => a.rank - b.rank).map((r) => (
                <li key={r.task_id}><strong>{r.title}</strong><p className="muted small-text">{r.reason}</p></li>
              ))}
            </ul>
          )}
        </details>

        <details className="card fold">
          <summary><h2>Registro de acciones</h2></summary>
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
        </details>

        <div className="card"><DevicePush /></div>
      </>}
    </section>
  );
}

// ------------------------------------------------------------------ day card: orb + next action + brief summary
type OrbState = "clear" | "soon" | "overdue";
const ORB: Record<OrbState, { tint: Tint; energy: number; label: string }> = {
  clear: { tint: "violet", energy: 0.12, label: "Sin pendientes" },
  soon: { tint: "cyan", energy: 0.75, label: "Aviso próximo" },
  overdue: { tint: "copper", energy: 0.5, label: "Aviso vencido" },
};

function DayCard({ summary, data, pending, snoozed, findTask, busy, onDone, onSnoozed }: {
  summary: DailySummary; data: TodayResp; pending: Reminder[]; snoozed: Reminder[]; findTask: (id: string) => Task | null; busy: Set<string>;
  onDone: (t: Task) => void; onSnoozed: (msg: string) => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 30_000); return () => window.clearInterval(t); }, []);

  // "Por atender" = overdue or past-time today, minus tasks whose reminder the user snoozed (that choice wins).
  const later = new Set(snoozed.filter((r) => Date.parse(r.snoozed_until!) > now).map((r) => r.task_id));
  const overdueN = [...data.overdue, ...data.today.filter((t) => t.due_at && Date.parse(t.due_at) <= now)]
    .filter((t) => isOpen(t) && !later.has(t.task_id)).length;
  // Next timed moment: an open task's due time or a snoozed reminder coming back.
  const soonest = [
    ...[...data.today, ...data.upcoming].filter((t) => isOpen(t) && t.due_at && Date.parse(t.due_at) > now).map((t) => Date.parse(t.due_at!)),
    ...snoozed.map((r) => Date.parse(r.snoozed_until!)).filter((t) => t > now),
  ].sort((a, b) => a - b)[0];
  const minsToSoon = soonest != null && soonest - now <= SOON_MS ? Math.max(1, Math.round((soonest - now) / 60_000)) : null;
  const state: OrbState = pending.length || overdueN ? "overdue" : minsToSoon != null ? "soon" : "clear";
  const o = ORB[state];

  // The one next action: a reminder that is ringing now, else what the server recommends.
  const ringing = pending[0] ?? null;
  const next = (ringing && findTask(ringing.task_id)) || (summary.next && findTask(summary.next.task_id)) || summary.next;
  const why = ringing ? "Aviso sonando ahora" : next?.due_date ? fmtWhen(next) : "Sin fecha";
  const coming = firstOfSeries(summary.upcoming).slice(0, 3);
  const jump = (id: string) => { const el = document.getElementById(id); el?.scrollIntoView({ block: "start" }); el?.focus({ preventScroll: true }); };

  return (
    <section className={`card day day-${state}`} aria-labelledby="day-title">
      <div className="day-orb">
        <Orb size={128} tint={o.tint} energy={o.energy}>
          <span className="reminders-count" aria-hidden="true">{state === "overdue" ? pending.length || overdueN : state === "soon" ? `${minsToSoon}′` : ""}</span>
        </Orb>
      </div>
      <div className="day-body">
        <p className="eyebrow" role="status" aria-live="polite">
          {o.label}{state === "soon" ? ` · en ${minsToSoon} min` : state === "overdue" ? ` · ${pending.length || overdueN} por atender` : ""}
        </p>
        <h2 id="day-title">{next ? <>Ahora: {next.title}</> : "Nada pendiente ahora"}</h2>
        {next ? <p className="muted">{why}{next.recurrence ? ` · ↻ ${describeRecurrence(next.recurrence, next.due_date)}` : ""}</p>
          : <p className="muted">Buen momento para descansar o adelantar algo.</p>}
        {next && (
          <div className="day-actions">
            {next.series_id && next.due_date && next.due_date > data.date
              ? <p className="muted small-text">Toca el {fmtWhen(next)}. Podrás marcarla ese día.</p>
              : <button className="primary" disabled={busy.has(next.task_id) || !isOpen(next) || next.status === "draft"} onClick={() => onDone(next)}>
                  {next.recurrence ? "Hecha esta vez" : "Hecha"}
                </button>}
            {ringing && <SnoozeControls reminder={ringing} onDone={onSnoozed} />}
          </div>
        )}
        <ul className="day-counts" aria-label="Resumen del día">
          <li><button type="button" className="chip" onClick={() => jump("sec-overdue")}><b>{summary.counts.overdue}</b> vencidas</button></li>
          <li><button type="button" className="chip" onClick={() => jump("sec-today")}><b>{summary.counts.pending}</b> pendientes hoy</button></li>
          <li><button type="button" className="chip" onClick={() => jump("sec-upcoming")}><b>{summary.counts.upcoming}</b> próximas</button></li>
        </ul>
        {coming.length > 0 && (
          <div className="day-coming">
            <h3>Próximos compromisos</h3>
            <ul>{coming.map((t) => <li key={t.task_id}><span className="when">{fmtWhen(t)}</span> {t.title}</li>)}</ul>
          </div>
        )}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ shared task fields (create + edit)
type Draft = { title: string; description: string; date: string; time: string; priority: Priority; kind: Kind; repeat: "none" | Freq; weekdays: Weekday[]; until: string };
const draftOf = (t?: Task): Draft => ({
  title: t?.title ?? "", description: t?.description ?? "", date: t?.due_date ?? "", time: t?.due_time?.slice(0, 5) ?? "",
  priority: t?.priority ?? 3, kind: t?.kind ?? "personal", repeat: t?.recurrence?.freq ?? "none",
  weekdays: t?.recurrence?.weekdays ?? [], until: t?.recurrence?.until ?? "",
});
const recurrenceOf = (d: Draft): Recurrence | null => d.repeat === "none" ? null : {
  freq: d.repeat, interval: 1, ...(d.repeat === "weekly" ? { weekdays: d.weekdays.length ? d.weekdays : d.date ? [isoWeekday(d.date)] : [] } : {}), until: d.until || null,
};
function problem(d: Draft): string | null {
  if (!d.title.trim()) return "Escribe un título.";
  if (d.repeat !== "none" && !d.date) return "Para repetir, elige la primera fecha.";
  if (d.until && d.date && d.until < d.date) return "La repetición no puede terminar antes de empezar.";
  const r = recurrenceOf(d);
  if (r?.freq === "weekly" && d.date && !r.weekdays!.includes(isoWeekday(d.date))) return "La primera fecha debe caer en uno de los días elegidos.";
  return null;
}
const fieldsOf = (d: Draft): Fields => ({ title: d.title.trim(), description: d.description, due_date: d.date || null, due_time: d.date && d.time ? d.time : null,
  priority: d.priority, kind: d.kind, recurrence: recurrenceOf(d) });

function TaskFields({ d, set, idp, withDescription, lockedRule }: { d: Draft; set: (p: Partial<Draft>) => void; idp: string; withDescription?: boolean; lockedRule?: boolean }) {
  const rec = recurrenceOf(d);
  const toggleDay = (w: Weekday) => {
    const base = d.weekdays.length ? d.weekdays : d.date ? [isoWeekday(d.date)] : [];
    const next = base.includes(w) ? base.filter((x) => x !== w) : [...base, w];
    set({ weekdays: next.length ? next.sort() : base }); // keep at least one day
  };
  return (
    <div className="fields">
      {withDescription && <>
        <label className="sr-only" htmlFor={`${idp}-desc`}>Descripción</label>
        <textarea id={`${idp}-desc`} rows={2} value={d.description} onChange={(e) => set({ description: e.target.value })} placeholder="Notas (opcional)" />
      </>}
      <div className="field-row">
        <label className="field">Fecha <input type="date" value={d.date} onChange={(e) => set({ date: e.target.value })} /></label>
        <label className="field">Hora del aviso <input type="time" value={d.time} disabled={!d.date} onChange={(e) => set({ time: e.target.value })} /></label>
        {!lockedRule && <label className="field">Repetir
          <select value={d.repeat} onChange={(e) => set({ repeat: e.target.value as Draft["repeat"] })}>
            <option value="none">No se repite</option>
            {(Object.keys(FREQ_LABEL) as Freq[]).map((f) => <option key={f} value={f}>{FREQ_LABEL[f]}</option>)}
          </select>
        </label>}
      </div>
      {!lockedRule && d.repeat === "weekly" && (
        <fieldset className="weekdays">
          <legend>Días</legend>
          {WEEKDAYS.map(([w, short, long]) => {
            const on = (rec?.weekdays ?? []).includes(w);
            return <button key={w} type="button" className={`day-toggle${on ? " is-on" : ""}`} aria-pressed={on} aria-label={long} onClick={() => toggleDay(w)}>{short}</button>;
          })}
        </fieldset>
      )}
      {!lockedRule && d.repeat !== "none" && (
        <div className="field-row">
          <label className="field">Termina
            <select value={d.until ? "date" : "never"} onChange={(e) => set({ until: e.target.value === "date" ? (d.date || new Date().toISOString().slice(0, 10)) : "" })}>
              <option value="never">Nunca</option><option value="date">En una fecha</option>
            </select>
          </label>
          {d.until && <label className="field">Último día <input type="date" value={d.until} min={d.date || undefined} onChange={(e) => set({ until: e.target.value })} required /></label>}
        </div>
      )}
      {rec && !lockedRule && <p className="rec-preview small-text">↻ {describeRecurrence(rec, d.date)}{d.time ? ` · aviso a las ${d.time}` : " · sin aviso (añade una hora)"}. Al completar una vez, aparece la siguiente.</p>}
      <details className="more">
        <summary>Prioridad y tipo</summary>
        <div className="field-row">
          <label className="field">Prioridad
            <select value={d.priority} onChange={(e) => set({ priority: Number(e.target.value) as Priority })}>
              {([1, 2, 3, 4] as Priority[]).map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
            </select>
          </label>
          <label className="field">Tipo
            <select value={d.kind} onChange={(e) => set({ kind: e.target.value as Kind })}>
              <option value="personal">Personal</option><option value="work">Trabajo</option>
            </select>
          </label>
        </div>
      </details>
    </div>
  );
}

function QuickCreate({ onCreate, busy }: { onCreate: (p: Fields) => Promise<boolean>; busy: boolean }) {
  const [d, setD] = useState<Draft>(draftOf());
  const [more, setMore] = useState(false);
  const [err, setErr] = useState("");
  const idp = useId();
  const set = (p: Partial<Draft>) => setD((x) => ({ ...x, ...p }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const bad = problem(d);
    if (bad) { setErr(bad); return; }
    setErr("");
    if (await onCreate(fieldsOf(d))) { setD(draftOf()); setMore(false); }
  }
  return (
    <form className="card create" onSubmit={submit} aria-labelledby={`${idp}-h`}>
      <h2 id={`${idp}-h`} className="sr-only">Nueva tarea</h2>
      <div className="create-main">
        <label className="sr-only" htmlFor={`${idp}-title`}>Nueva tarea</label>
        <input id={`${idp}-title`} className="qc-title" value={d.title} onChange={(e) => set({ title: e.target.value })} placeholder="Nueva tarea…" required />
        <button className="primary" disabled={busy || !d.title.trim()}>{busy ? "Creando…" : "Crear"}</button>
      </div>
      <button type="button" className="ghost small" aria-expanded={more} aria-controls={`${idp}-more`} onClick={() => setMore(!more)}>
        {more ? "Menos opciones" : "Fecha, aviso y repetición"}
      </button>
      {more && <div id={`${idp}-more`}><TaskFields d={d} set={set} idp={idp} /></div>}
      {err && <p className="error small-text" role="alert">{err}</p>}
    </form>
  );
}

// ------------------------------------------------------------------ sections and rows
type RowProps = {
  today: string; disabledIds: Set<string>; highlight: string | null; reminders: Reminder[];
  onToggleDone: (t: Task, done: boolean) => void; onSave: (t: Task, changes: EditPayload) => void; onActivate: (t: Task) => void;
  onReorder: (ids: string[], i: number, dir: -1 | 1) => void; onSnoozed: (msg: string) => void; onStopped: (msg: string) => void;
};

function Section({ id, title, tasks, emptyText, collapsible, ...p }: RowProps & { id: string; title: string; tasks: Task[]; emptyText: string; collapsible?: boolean }) {
  const list = tasks.length === 0 ? <p className="muted">{emptyText}</p> : (
    <ul className="task-list">
      {tasks.map((t, i) => (
        <TaskRow key={t.task_id} task={t} canMoveUp={i > 0} canMoveDown={i < tasks.length - 1} {...p}
          reminder={p.reminders.find((r) => r.task_id === t.task_id && !r.read_at) ?? null}
          onMoveUp={() => p.onReorder(tasks.map((x) => x.task_id), i, -1)}
          onMoveDown={() => p.onReorder(tasks.map((x) => x.task_id), i, 1)} />
      ))}
    </ul>
  );
  const head = <h2>{title} {tasks.length > 0 && <span className="muted">({tasks.length})</span>}</h2>;
  if (collapsible) {
    const hasFocus = tasks.some((t) => t.task_id === p.highlight);
    return <details id={id} tabIndex={-1} className="card fold" open={hasFocus || undefined}><summary>{head}</summary>{list}</details>;
  }
  return <section id={id} tabIndex={-1} className="card" aria-label={title}>{head}{list}</section>;
}

function TaskRow({ task, today, disabledIds, highlight, reminder, canMoveUp, canMoveDown, onToggleDone, onSave, onActivate, onMoveUp, onMoveDown, onSnoozed, onStopped }: RowProps & {
  task: Task; reminder: Reminder | null; canMoveUp: boolean; canMoveDown: boolean; onMoveUp: () => void; onMoveDown: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [d, setD] = useState<Draft>(() => draftOf(task));
  const [err, setErr] = useState("");
  const idp = useId();
  const disabled = disabledIds.has(task.task_id);
  // A future occurrence of a series is completed on its day, not ahead of time.
  const ahead = !!task.series_id && !!task.due_date && !!today && task.due_date > today && task.status !== "done";
  const rec = task.recurrence ?? null;
  const done = task.status === "done";

  function save(e: React.FormEvent) {
    e.preventDefault();
    const bad = problem(d);
    if (bad) { setErr(bad); return; }
    const f = fieldsOf(d);
    onSave(task, { title: f.title, description: f.description, due_date: f.due_date, due_time: f.due_time, priority: f.priority,
      ...(!rec && f.recurrence ? { recurrence: f.recurrence } : {}) }); // an existing rule is immutable (409)
    setErr(""); setEditing(false);
  }
  const checkLabel = done ? `Reabrir «${task.title}»`
    : rec ? `Completar esta vez «${task.title}»${task.next_due ? `; la siguiente será ${fmtWhen(task.next_due)}` : ""}` : `Completar «${task.title}»`;

  return (
    <li id={`task-${task.task_id}`} tabIndex={-1} className={`task-row${highlight === task.task_id ? " is-focused" : ""}`}>
      <input type="checkbox" checked={done} disabled={disabled || ahead || task.status === "draft" || task.status === "cancelled"}
        title={ahead ? "Podrás completarla ese día" : undefined}
        onChange={(e) => onToggleDone(task, e.target.checked)} aria-label={checkLabel} />
      <div className="task-main">
        {editing ? (
          <form className="task-edit" onSubmit={save}>
            <label className="sr-only" htmlFor={`${idp}-title`}>Título</label>
            <input id={`${idp}-title`} value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })} required />
            <TaskFields d={d} set={(p) => setD((x) => ({ ...x, ...p }))} idp={idp} withDescription lockedRule={!!rec} />
            {rec && <StopSeries task={task} onStopped={onStopped} />}
            {err && <p className="error small-text" role="alert">{err}</p>}
            <div className="row">
              <button className="primary small" disabled={disabled}>Guardar</button>
              <button type="button" className="ghost small" onClick={() => { setEditing(false); setErr(""); }}>Cancelar</button>
            </div>
          </form>
        ) : (
          <>
            <span className={`task-title ${done ? "done" : ""}`}>{task.title}</span>
            {task.description && <p className="muted small-text">{task.description}</p>}
            <div className="task-meta">
              {task.due_date && <span className="when">{fmtWhen(task)}</span>}
              {rec && <span className="badge badge-rec" title="Tarea recurrente">↻ {describeRecurrence(rec, task.due_date)}</span>}
              {(task as Shown).later ? <span className="muted">+{(task as Shown).later} más esta semana</span> : null}
              {task.priority <= 2 && <span className="badge">{PRIORITY_LABEL[task.priority]}</span>}
              <span className="badge">{KIND_LABEL[task.kind]}</span>
              <PrivBadge p={task.privacy} />
              {task.status === "draft" && <span className="draft-flag">Borrador: aún no es una tarea activa</span>}
            </div>
            {rec && !done && (
              <p className="rec-next small-text">
                {task.next_due ? <>Al completarla, vuelve <strong>{fmtWhen(task.next_due)}</strong>.</> : "Al completarla, se programa la siguiente."}
              </p>
            )}
            {reminder && !done && <SnoozeControls reminder={reminder} onDone={onSnoozed} compact />}
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
        {task.status === "draft" && <button className="small" onClick={() => onActivate(task)} disabled={disabled}>Activar</button>}
        {!editing && task.status !== "cancelled" && <button className="ghost small" onClick={() => { setD(draftOf(task)); setEditing(true); }} disabled={disabled}>Editar</button>}
        <div className="row reorder">
          <button className="ghost small" onClick={onMoveUp} disabled={disabled || !canMoveUp} aria-label={`Subir «${task.title}»`}>▲</button>
          <button className="ghost small" onClick={onMoveDown} disabled={disabled || !canMoveDown} aria-label={`Bajar «${task.title}»`}>▼</button>
        </div>
      </div>
    </li>
  );
}

// The rule of a series can't be edited (the contract keeps history unambiguous): it can only be stopped.
function StopSeries({ task, onStopped }: { task: Task; onStopped: (msg: string) => void }) {
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function stop() {
    setBusy(true); setErr("");
    try { await api(`/api/series/${task.series_id}/stop`, "POST"); onStopped(`Serie detenida: «${task.title}». El historial se conserva.`); }
    catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }
  return (
    <div className="stop-series">
      <p className="muted small-text">↻ {describeRecurrence(task.recurrence!, task.due_date)}. Los cambios valen solo para esta vez; la repetición no se edita.</p>
      {!ask ? <button type="button" className="ghost small" disabled={!task.series_id} onClick={() => setAsk(true)}>Detener la repetición…</button> : (
        <div className="row" role="group" aria-label="Confirmar detener la repetición">
          <span className="small-text">Se cancelan las próximas. Las hechas quedan en el historial.</span>
          <button type="button" className="danger small" disabled={busy} onClick={stop}>{busy ? "Deteniendo…" : "Detener"}</button>
          <button type="button" className="ghost small" onClick={() => setAsk(false)}>No</button>
        </div>
      )}
      {err && <p className="error small-text" role="alert">{err}</p>}
    </div>
  );
}
