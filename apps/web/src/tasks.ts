// Shared Task/Action contract (backend: services/tasks). Single source of truth so
// Today.tsx and Chat.tsx don't redeclare the same shapes.
export type Privacy = "PUBLIC" | "INTERNAL" | "PRIVATE";
export type TaskStatus = "draft" | "open" | "in_progress" | "done" | "cancelled";
export type Priority = 1 | 2 | 3 | 4;
export type Kind = "personal" | "work";
export type Origin = "user" | "chat" | "evidence";

export type Source = { kind: "log" | "document"; title: string; location: string | null; excerpt: string | null; privacy: string };

export type Task = {
  task_id: string; title: string; description: string; status: TaskStatus; priority: Priority; kind: Kind;
  due_date: string | null; due_time: string | null; timezone: string; origin: Origin; privacy: Privacy;
  due_at?: string | null;
  recurrence?: Recurrence | null; series_id?: string | null; next_due?: NextDue | null;
  project: string | null; parent_id: string | null; position: number; sources: Source[];
  created_at: string; updated_at: string; completed_at: string | null; version: number;
};

export type ActionLevel = "C0" | "C1" | "C2" | "C3";
export type ActionStatus = "proposed" | "awaiting_authorization" | "running" | "done" | "failed" | "needs_review" | "cancelled";
export type Action = {
  action_id: string; kind: string; level: ActionLevel; status: ActionStatus; summary: string;
  task_id: string | null; origin: Origin; error: string | null; created_at: string; updated_at: string;
};

export const PRIORITY_LABEL: Record<Priority, string> = { 1: "Urgente", 2: "Alta", 3: "Normal", 4: "Baja" };
export const KIND_LABEL: Record<Kind, string> = { personal: "Personal", work: "Trabajo" };
export const ACTION_STATUS_LABEL: Record<ActionStatus, string> = {
  done: "Hecho", failed: "Fallido", needs_review: "Requiere revisión", awaiting_authorization: "Pendiente de autorización",
  proposed: "Propuesta", running: "En curso", cancelled: "Cancelada",
};

// ---- Stage 2: recurrence, reminders, daily summary (alice-coordination/API_CONTRACT.md, etapa 2)
export type Freq = "daily" | "weekly" | "monthly";
export type Weekday = 1 | 2 | 3 | 4 | 5 | 6 | 7; // ISO: 1 = lunes … 7 = domingo
export type Recurrence = { freq: Freq; interval?: number; weekdays?: Weekday[]; until?: string | null };
export type NextDue = { due_date: string; due_time: string | null };

export type Reminder = {
  reminder_id: number; task_id: string; title: string; scheduled_at: string; timezone: string;
  read_at: string | null; snoozed_until?: string | null;
};
export type Inbox = { enabled: boolean; unread: number; items: Reminder[] };

export type DailySummary = {
  date: string; timezone: string; counts: { pending: number; overdue: number; upcoming: number };
  next: Task | null; overdue: Task[]; today: Task[]; upcoming: Task[]; generated_at?: string;
};

export const WEEKDAYS: [Weekday, string, string][] = [
  [1, "L", "lunes"], [2, "M", "martes"], [3, "X", "miércoles"], [4, "J", "jueves"], [5, "V", "viernes"], [6, "S", "sábado"], [7, "D", "domingo"],
];
export const FREQ_LABEL: Record<Freq, string> = { daily: "Cada día", weekly: "Cada semana", monthly: "Cada mes" };

const listEs = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} y ${xs[xs.length - 1]}`);

export const fmtDay = (date: string) =>
  new Date(date + "T00:00:00").toLocaleDateString("es-CL", { weekday: "short", day: "numeric", month: "short" });
export const fmtWhen = (d: NextDue | { due_date: string | null; due_time: string | null }) =>
  d.due_date ? `${fmtDay(d.due_date)}${d.due_time ? ` · ${d.due_time.slice(0, 5)}` : ""}` : "sin fecha";

// "Cada semana: lunes y miércoles · hasta 30 nov" — short enough for a badge or a form preview.
export function describeRecurrence(r: Recurrence, dueDate?: string | null): string {
  const n = r.interval && r.interval > 1 ? r.interval : 1;
  let s = r.freq === "daily" ? (n > 1 ? `Cada ${n} días` : "Cada día")
    : r.freq === "weekly" ? `${n > 1 ? `Cada ${n} semanas` : "Cada semana"}${r.weekdays?.length ? `: ${listEs(WEEKDAYS.filter(([d]) => r.weekdays!.includes(d)).map(([, , l]) => l))}` : ""}`
    : `${n > 1 ? `Cada ${n} meses` : "Cada mes"}${dueDate ? `, el día ${Number(dueDate.slice(8, 10))}` : ""}`;
  if (r.until) s += ` · hasta ${new Date(r.until + "T00:00:00").toLocaleDateString("es-CL", { day: "numeric", month: "short" })}`;
  return s;
}

export const isoWeekday = (date: string) => (((new Date(date + "T00:00:00").getDay() + 6) % 7) + 1) as Weekday;
