// Shared types and small helpers used by every Knowledge view (Órbita, Mapa, Lista).
import type { Privacy } from "../Chat";

export type DocStatus = "pending" | "processing" | "ready" | "failed";
export type Doc = {
  document_id: string; original_name: string; size_bytes: number; kind: string; ingested_at: string; privacy: Privacy;
  verification: string; status: DocStatus; status_detail: string | null; chunks: number | null; version: number;
};
export type Upload = { id: string; name: string; pct: number; state: "uploading" | "done" | "error"; msg?: string };

export const ACCEPT = ".pdf,.md,.markdown,.txt,.log,.csv,.xlsx";
export const STATUS_ES: Record<DocStatus, string> = { pending: "en cola", processing: "procesando", ready: "listo", failed: "fallido" };

export const reducedMotion = (): boolean => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// Document actions shared by every view that can show a detail panel (Órbita, Mapa) — the delete
// confirmation, cancel-processing and download actions all route back to the same handlers in
// Knowledge.tsx, which owns the actual API calls and the single `confirm` (delete) state.
export interface DocActions {
  confirm: string | null;
  onAskDelete: (id: string) => void;
  onConfirmDelete: (id: string) => void;
  onCancelDelete: () => void;
  onCancelProcessing: (id: string) => void;
}

// Kind groups drive the orbit rings and the map's node colour: four families, matching what ingestion
// actually produces (services/ingestion/extract.py KINDS), plus a catch-all for anything unexpected.
export type KindGroup = "pdf" | "texto" | "hojas" | "logs" | "otros";
const GROUP_BY_KIND: Record<string, KindGroup> = {
  pdf: "pdf", markdown: "texto", text: "texto", csv: "hojas", xlsx: "hojas", log: "logs",
};
export const kindGroup = (kind: string): KindGroup => GROUP_BY_KIND[kind] ?? "otros";
export const GROUP_LABEL: Record<KindGroup, string> = {
  pdf: "PDF", texto: "Texto y markdown", hojas: "Hojas de cálculo", logs: "Registros", otros: "Otros",
};
// Reuses the chart series tokens from theme.css instead of inventing new colours for the graph.
export const GROUP_COLOR_VAR: Record<KindGroup, string> = {
  pdf: "--series-1", texto: "--series-3", hojas: "--series-6", logs: "--series-2", otros: "--series-4",
};
