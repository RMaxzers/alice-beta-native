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
