// Demo-only API for design capture (Figma) and visual QA. Serves synthetic fixtures built from
// data/samples; never touches the real backend, storage or any private data. Loaded only by
// vite.demo.config.ts, so it cannot reach the production build.
//
// Scenario switch: GET /__demo/set?mode=normal|empty|error&auth=1|0&contract=1|0 (state lives in this process).
// contract=1 (default) serves API contract v1 (conversations, identity, file actions); 0 mimics the pre-v1 backend.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

const SAMPLES = resolve(__dirname, "../../../data/samples");
const NOW = new Date("2026-09-28T10:30:00-03:00");
const iso = (minAgo = 0) => new Date(NOW.getTime() - minAgo * 60_000).toISOString();
const day = (d: number) => new Date(NOW.getTime() + d * 86_400_000).toISOString().slice(0, 10);

const state = { mode: "normal" as "normal" | "empty" | "error", auth: true, contract: true };

// ------------------------------------------------------------------ contract v1 (alice-coordination/API_CONTRACT.md)
type Stored = { message_id: string; role: "user" | "assistant"; content: string; privacy: string; created_at: string; status: string; client_request_id: string };
type Conv = { conversation_id: string; title: string; privacy: string; created_at: string; updated_at: string; messages: Stored[] };
const RANKP: Record<string, number> = { PUBLIC: 0, INTERNAL: 1, PRIVATE: 2 };
const stricter = (a: string, b: string) => (RANKP[b] > RANKP[a] ? b : a);
const convs = new Map<string, Conv>();
const turns = new Map<string, { hash: string; events: object[] }>(); // client_request_id → replay
const fileOps: (Record<string, unknown> & { conversation_id: string })[] = [];
let n = 0;
const nid = (p: string) => `${p}-demo-${++n}`;
function seedConversation() {
  const c: Conv = { conversation_id: "conv-demo-dhcp", title: "Red de invitados y DHCP", privacy: "INTERNAL", created_at: iso(300), updated_at: iso(240), messages: [] };
  const add = (role: Stored["role"], content: string, status: string, ago: number) =>
    c.messages.push({ message_id: nid("msg"), role, content, privacy: "INTERNAL", created_at: iso(ago), status, client_request_id: nid("req") });
  add("user", "¿Qué VLAN usa la red de invitados?", "complete", 300);
  add("assistant", "La red de invitados usa la **VLAN 30** con arrendamiento DHCP de **4 horas**.", "complete", 299);
  add("user", "Resume el log de ingestión", "interrupted", 240);
  convs.set(c.conversation_id, c);
}
seedConversation();
const summary = ({ messages: _m, ...c }: Conv) => c;

// ------------------------------------------------------------------ fixtures
const docs = [
  { document_id: "doc-manual", original_name: "manual-red-laboratorio-demo.pdf", size_bytes: 1499, kind: "pdf", privacy: "INTERNAL", chunks: 2 },
  { document_id: "doc-guia", original_name: "guia-dhcp-laboratorio-demo.md", size_bytes: 878, kind: "markdown", privacy: "INTERNAL", chunks: 5 },
  { document_id: "doc-inventario", original_name: "inventario-laboratorio-demo.csv", size_bytes: 1074, kind: "csv", privacy: "INTERNAL", chunks: 12 },
  { document_id: "doc-log", original_name: "ingestion-laboratorio-demo.log", size_bytes: 850, kind: "log", privacy: "PRIVATE", chunks: 10 },
  { document_id: "doc-notas", original_name: "notas-proyecto-demo.txt", size_bytes: 2310, kind: "text", privacy: "INTERNAL", chunks: 3 },
  { document_id: "doc-vlan", original_name: "plan-vlan-demo.xlsx", size_bytes: 9120, kind: "xlsx", privacy: "INTERNAL", chunks: 8 },
  { document_id: "doc-cola", original_name: "presupuesto-demo.pdf", size_bytes: 48210, kind: "pdf", privacy: "INTERNAL", chunks: null, status: "processing" },
  { document_id: "doc-roto", original_name: "escaneo-cifrado-demo.pdf", size_bytes: 20480, kind: "pdf", privacy: "PRIVATE", chunks: null, status: "failed",
    status_detail: "PDF cifrado no soportado" },
].map((d, i) => ({ status: "ready", status_detail: null, verification: "unverified", version: 1, ingested_at: iso(60 * (i + 2)), ...d }));

const files: Record<string, [string, string]> = {
  "doc-manual": ["manual-red-laboratorio-demo.pdf", "application/pdf"],
  "doc-guia": ["guia-dhcp-laboratorio-demo.md", "text/markdown; charset=utf-8"],
  "doc-inventario": ["inventario-laboratorio-demo.csv", "text/csv; charset=utf-8"],
  "doc-log": ["ingestion-laboratorio-demo.log", "text/plain; charset=utf-8"],
};

let seq = 0;
const task = (title: string, o: Record<string, unknown> = {}) => ({
  task_id: `t-${++seq}`, title, description: "", status: "open", priority: 3, kind: "personal", due_date: null, due_time: null,
  timezone: "America/Santiago", origin: "user", privacy: "INTERNAL", project: null, parent_id: null, position: seq, sources: [],
  created_at: iso(3000), updated_at: iso(600), completed_at: null, version: 1, ...o,
});
const overdue = [task("Renovar soporte de router-demo-01", { due_date: day(-2), priority: 2, kind: "work" })];
const today = [
  task("Revisar arrendamiento DHCP de invitados", { due_date: day(0), due_time: "11:00", priority: 1, kind: "work", origin: "chat" }),
  task("Preparar demo de Alice", { due_date: day(0), priority: 2 }),
  task("Investigar timeouts de embeddings", { due_date: day(0), kind: "work", origin: "evidence", privacy: "PRIVATE",
    sources: [{ kind: "log", title: "ingestion-laboratorio-demo.log", location: "línea 4", excerpt: "ERROR timeout al generar embeddings", privacy: "PRIVATE" }] }),
];
const upcoming = [task("Inventariar switches de Planta 1", { due_date: day(3), kind: "work" }), task("Comprar cable de consola", { due_date: day(5), priority: 4 })];
const undated = [task("Leer sobre VLAN privadas", { priority: 4 })];
const drafts = [task("Documentar rango de infraestructura", { status: "draft", origin: "chat" })];
const action = (summary: string, status: string, level: string, minAgo: number, error: string | null = null) => ({
  action_id: `a-${++seq}`, kind: "create_task", level, status, summary, task_id: null, origin: "chat", error, created_at: iso(minAgo), updated_at: iso(minAgo),
});

const health = () => {
  const h = (state: string, detail: string) => ({ state, detail, checked_at: iso() });
  const down = state.mode === "error";
  return {
    alice_api: h("healthy", "respondiendo"), ollama: down ? h("unavailable", "conexión rechazada") : h("healthy", "v0.12.3"),
    qdrant: h("healthy", "ok"), prometheus: h("healthy", "ok"), grafana: h("healthy", "ok"), windows_exporter: h("healthy", "ok"),
    gpu: h("healthy", "RTX 3070 Laptop VRAM 2410/8192 MiB"), router: h("healthy", "reglas + semántico + clasificador"),
    openrouter: h("configured_not_tested", "clave presente, sin llamada hoy"), web: h("not_configured", "sin proveedor de búsqueda"),
    hermes: h("disabled", "deshabilitado"), docker: h("disabled", "deshabilitado por configuración"),
    email: h("disabled", "Integración opcional fuera del núcleo Beta 0.1"), notebooklm: h("disabled", "Integración opcional fuera del núcleo Beta 0.1"),
  };
};
const metric = (value: number, unit: string) => ({ value, unit, age_s: 4 });
const recent = [
  ["LOCAL_RAG", "ollama", "qwen3:4b-instruct-2507-q4_K_M", "done", 3.2, 2],
  ["LOCAL_SIMPLE", "ollama", "qwen3:4b-instruct-2507-q4_K_M", "done", 1.4, 9],
  ["STRUCTURED_QUERY", "ollama", "qwen3:4b-instruct-2507-q4_K_M", "done", 2.1, 16],
  ["OBSERVABILITY", null, null, "done", 0.6, 31],
  ["CLOUD_CHEAP", "openrouter", null, "blocked", null, 44],
  ["LOG_ANALYSIS", "ollama", "qwen3:4b-instruct-2507-q4_K_M", "error", 12.8, 58],
].map(([route, provider, model, status, duration_s, ago], i) => ({ request_id: `req-demo-${i + 1}`, started_at: iso(ago as number), route, provider, model, status, duration_s }));

const series = (base: number, amp: number, minutes: number) => {
  const end = Math.floor(NOW.getTime() / 1000), step = Math.max(15, (minutes * 60) / 120);
  const pts: [number, number][] = [];
  for (let t = end - minutes * 60; t <= end; t += step) pts.push([t, +(base + amp * Math.sin(t / 300) + amp * 0.3 * Math.sin(t / 47)).toFixed(2)]);
  return pts;
};
const RANGE: Record<string, [number, number, string]> = {
  host_cpu_percent: [22, 12, "%"], host_mem_used_bytes: [9.1e9, 6e8, "bytes"], gpu_util_percent: [18, 15, "%"],
  gpu_mem_used_bytes: [2.5e9, 3e8, "bytes"], gpu_temp_c: [54, 4, "°C"], alice_p95_latency_s: [2.8, 0.9, "s"],
};

const routes: Record<string, (q: URLSearchParams, body: any) => unknown> = {
  "GET /api/session": () => ({ user: "demo", csrf: "demo-csrf" }),
  "POST /api/login": (_q, b) => {
    if (b?.password !== "demo") throw [401, "Usuario o contraseña incorrectos"];
    state.auth = true; return { user: b.username || "demo", csrf: "demo-csrf" };
  },
  "POST /api/logout": () => { state.auth = false; return { ok: true }; },
  "GET /api/settings": () => ({
    local_only: true, cloud_enabled: false, budget_per_request_usd: 0.05, budget_daily_usd: 1, timezone: "America/Santiago", max_upload_mb: 50,
    credentials: { openrouter: "configurada", tavily: "sin configurar" }, features: { voice: true, memory: true, notebooklm: false, web_research: false },
  }),
  "PUT /api/settings": () => ({ ok: true }),
  "GET /api/today": () => {
    const empty = state.mode === "empty";
    return {
      date: day(0), timezone: "America/Santiago", overdue: empty ? [] : overdue, today: empty ? [] : today, upcoming: empty ? [] : upcoming,
      undated: empty ? [] : undated, drafts: empty ? [] : drafts,
      recommendations: empty ? [] : [
        { task_id: today[0].task_id, title: today[0].title, reason: "Vence a las 11:00 y es urgente", rank: 1 },
        { task_id: overdue[0].task_id, title: overdue[0].title, reason: "Atrasada 2 días", rank: 2 },
      ],
      recent_actions: empty ? [] : [
        action("Tarea creada desde el chat: Revisar arrendamiento DHCP", "done", "C1", 25),
        action("Enviar resumen a NotebookLM", "awaiting_authorization", "C2", 40),
        action("Crear tarea desde el log de ingestión", "failed", "C1", 90, "El documento se eliminó antes de crear la tarea"),
      ],
    };
  },
  "GET /api/documents": () => (state.mode === "empty" ? [] : docs),
  "GET /api/knowledge/map": () => {
    const ready = state.mode === "empty" ? [] : docs.filter((d) => d.status === "ready");
    return {
      nodes: ready.map((d) => ({ id: d.document_id, name: d.original_name, kind: d.kind, privacy: d.privacy, chunks: d.chunks ?? 0 })),
      edges: state.mode === "empty" ? [] : [
        ["doc-manual", "doc-guia", 0.82], ["doc-guia", "doc-inventario", 0.61], ["doc-manual", "doc-vlan", 0.74],
        ["doc-log", "doc-notas", 0.55], ["doc-inventario", "doc-vlan", 0.58],
      ].map(([source, target, similarity]) => ({ source, target, similarity })),
    };
  },
  "GET /api/datasets/doc-inventario/rows": () => {
    const [head, ...lines] = readFileSync(resolve(SAMPLES, "inventario-laboratorio-demo.csv"), "utf8").trim().split(/\r?\n/);
    return { columns: head.split(","), rows: lines.map((l) => l.split(",")), total: lines.length, truncated: false };
  },
  "GET /api/integrations/notebooklm/status": () => ({ enabled: false, detail: "Integración opcional apagada" }),
  "GET /api/observability/overview": () => ({
    health: health(), grafana_url: "http://127.0.0.1:3000/d/alice-overview",
    metrics: state.mode === "error" ? { host_cpu_percent: { value: null, error: "Prometheus sin datos" } } : {
      host_cpu_percent: metric(23.4, "%"), host_mem_used_bytes: metric(9.3e9, "bytes"), host_mem_total_bytes: metric(17.1e9, "bytes"),
      gpu_util_percent: metric(17, "%"), gpu_mem_used_bytes: metric(2.53e9, "bytes"), gpu_mem_total_bytes: metric(8.59e9, "bytes"), gpu_temp_c: metric(55, "°C"),
    },
    usage_today: { by_provider: { ollama: 14, openrouter: 0 }, spent: { accounted: 0, reserved_open: 0, unknown_cost_calls: 0 } },
    recent_requests: state.mode === "empty" ? [] : recent,
  }),
  "GET /api/observability/range": (q) => {
    const m = q.get("metric") || "host_cpu_percent", minutes = Number(q.get("minutes") || 60);
    const [base, amp, unit] = RANGE[m] ?? [10, 5, ""];
    return { metric: m, unit, description: `Serie sintética de ${m}`, coverage: { fraction: 1, first: null, last: null, gaps: [] },
      series: [{ labels: {}, points: series(base, amp, minutes) }] };
  },
  "GET /api/models": () => ({
    ollama_reachable: state.mode !== "error",
    aliases: [
      { alias: "local-fast", provider: "ollama", model: "qwen3:4b-instruct-2507-q4_K_M", location: "local", available: true, loaded: true, vram_bytes: 3.1e9, size_bytes: 2.5e9, state: "healthy" },
      { alias: "local-code", provider: "ollama", model: "qwen2.5-coder:7b", location: "local", available: true, loaded: false, size_bytes: 4.7e9, state: "healthy" },
      { alias: "embed", provider: "ollama", model: "bge-m3", location: "local", available: true, loaded: true, vram_bytes: 1.2e9, size_bytes: 1.2e9, state: "healthy" },
      { alias: "cloud-cheap", provider: "openrouter", model: "demo/cheap-model", location: "cloud", available: false, state: "configured_not_tested",
        detail: "Cloud deshabilitado", pricing: { usd_per_mtok_in: 0.1, usd_per_mtok_out: 0.4 } },
    ],
    routes: { LOCAL_SIMPLE: "local-fast", LOCAL_CODE: "local-code", LOCAL_RAG: "local-fast", CLOUD_CHEAP: "cloud-cheap" },
    future_providers: { anthropic: "pendiente", tavily: "pendiente" },
  }),
  "GET /api/system": () => ({
    health: health(), local_only: true, version: "0.1.0-beta.1", grafana_local: "http://127.0.0.1:3000",
    budget: { per_request_usd: 0.05, daily_usd: 1, today: { accounted: 0, reserved_open: 0, unknown_cost_calls: 0 } },
    remote: { public_origin: null, via_proxy: false },
  }),
  "GET /api/memory/status": () => ({ enabled: true, user_enabled: true, sidecar_healthy: state.mode !== "error", count: state.mode === "empty" ? 0 : 3 }),
  "GET /api/memory": () => ({
    total: state.mode === "empty" ? 0 : 3,
    items: state.mode === "empty" ? [] : [
      { id: "m1", text: "Prefiere respuestas cortas en español", context: "preferencias", date: day(-3) },
      { id: "m2", text: "El servidor DHCP de la demo es dhcp-demo-01 (192.168.10.2)", context: "hecho verificado", date: day(-6) },
      { id: "m3", text: "Está preparando una demo de Alice para esta semana", context: "chat", date: day(-1) },
    ],
  }),
  "POST /api/memory/toggle": () => ({ ok: true }),
  "GET /api/voice/status": () => ({ enabled: true, tts: { reachable: true }, stt: { model: "whisper-small", device: "cuda", loaded: false } }),
  "POST /api/tasks/reorder": () => ({ ok: true, event_id: 1 }),
  "GET /api/identity": () => {
    if (!state.contract) throw [404, "Not Found"];
    return { backend_id: "demo-backend", executor_name: "PC-DEMO", api_contract: "1", file_action: { enabled: true, root_label: "Mi carpeta de Alice" } };
  },
  "GET /api/conversations": () => [...convs.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(summary),
  "POST /api/conversations": (_q, b) => {
    const c: Conv = { conversation_id: nid("conv"), title: b?.title ?? "Nueva conversación", privacy: b?.privacy ?? "PRIVATE",
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(), messages: [] };
    convs.set(c.conversation_id, c); return summary(c);
  },
  "GET /api/file-actions": (q) => fileOps.filter((o) => !q.get("conversation_id") || o.conversation_id === q.get("conversation_id")).reverse(),
};

// Chat through the v1 contract: conversation event first, server-kept history, idempotent client_request_id.
function fileOpFor(convId: string, filename: string) {
  const name = filename.toLowerCase();
  const status = name.includes("existente") ? "failed" : name.includes("revisar") ? "needs_review" : "done";
  const op = {
    operation_id: nid("op"), owner: "demo", conversation_id: convId, tool: "file.create_text", destination: `C:\\AliceDemo\\${filename}`,
    executor_name: "PC-DEMO", status, privacy: "INTERNAL", created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    verification: status === "done" ? { verified: true, sha256: "9f2c5e0b7a41d3c8e6f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3", bytes: 214 } : null,
    error: status === "failed" ? "El archivo ya existe; no se sobrescribe" : status === "needs_review" ? "No se pudo confirmar la escritura" : null,
  };
  fileOps.push(op);
  return op;
}

function chatV1(body: any): { status: number; events?: object[]; detail?: string } {
  const key = body?.client_request_id;
  if (!key) return { status: 422, detail: "client_request_id requerido" };
  const { client_request_id: _k, ...rest } = body;
  const hash = JSON.stringify(rest);
  const old = turns.get(key);
  if (old) return old.hash === hash ? { status: 200, events: old.events } : { status: 409, detail: "client_request_id ya vinculado a otra petición" };
  let c = body.conversation_id ? convs.get(body.conversation_id) : undefined;
  if (body.conversation_id && !c) return { status: 404, detail: "Conversación no encontrada" };
  const at = new Date().toISOString();
  if (!c) {
    c = { conversation_id: nid("conv"), title: String(body.message).slice(0, 80), privacy: body.privacy, created_at: at, updated_at: at, messages: [] };
    convs.set(c.conversation_id, c);
  }
  c.privacy = stricter(c.privacy, body.privacy);
  const conv = c;
  const file = /guarda .* como ([\w.-]+\.(?:md|txt))/i.exec(body.message)?.[1];
  let events: any[];
  if (file) {
    const answer = [...conv.messages].reverse().find((m) => m.role === "assistant" && m.status === "complete");
    if (!answer) events = [{ type: "error", code: "no_summary", message: "Esta conversación todavía no tiene una respuesta completa que guardar." }];
    else {
      const op = fileOpFor(conv.conversation_id, file);
      const msg = op.status === "done" ? `Archivo creado y verificado: ${op.destination} en ${op.executor_name}.` : `Operación ${op.operation_id} en ${op.executor_name}: ${op.error}.`;
      events = [{ type: "action", action: op, message: msg }, ...(op.status === "done" ? [done()] : [{ type: "error", code: "action_unverified", message: msg }])];
    }
  } else events = chatScript(body.message, body);
  for (const ev of events) if (ev.type === "route") conv.privacy = stricter(conv.privacy, ev.decision.privacy);
  const last = events[events.length - 1] as any;
  const status = last.type === "error" ? "failed" : last.type === "authorization_required" ? "awaiting_authorization" : "complete";
  if (last.type === "done") Object.assign(last, { conversation_id: conv.conversation_id, client_request_id: key, privacy: conv.privacy, status });
  events = [{ type: "conversation", conversation_id: conv.conversation_id, client_request_id: key, privacy: conv.privacy }, ...events];
  const text = events.filter((e) => e.type === "token").map((e) => e.text).join("") + events.filter((e) => e.type === "action").map((e) => e.message).join("\n");
  conv.messages.push({ message_id: nid("msg"), role: "user", content: body.message, privacy: conv.privacy, created_at: at, status, client_request_id: key });
  if (text) conv.messages.push({ message_id: nid("msg"), role: "assistant", content: text, privacy: conv.privacy, created_at: at, status, client_request_id: key });
  conv.updated_at = at;
  turns.set(key, { hash, events });
  return { status: 200, events };
}

// ------------------------------------------------------------------ chat (NDJSON stream)
const route = (r: string, reason: string, privacy = "INTERNAL", extra = {}) =>
  ({ type: "route", decision: { route: r, reason, decided_by: "reglas", privacy, model_alias: "local-fast", confidence: 0.92, ...extra }, raised_by: [] });
const done = (privacy = "INTERNAL") => ({ type: "done", request_id: "req-demo-chat", provider: "ollama", model: "qwen3:4b-instruct-2507-q4_K_M",
  latency_s: 2.4, queue_s: 0.1, retrieval_s: 0.3, tokens_out: 96, cost_usd: 0, cost_state: "local", privacy });
const words = (s: string) => s.split(/(?<= )/).map((text) => ({ type: "token", text }));

function chatScript(msg: string, body: any = {}): object[] {
  const m = msg.toLowerCase();
  if (body.authorization_ticket)
    return [route("CLOUD_CHEAP", "autorizado una vez", "INTERNAL", { model_alias: "cloud-cheap" }),
      ...words("Respuesta de demostración desde la nube tras tu autorización (datos sintéticos)."),
      { ...done(), provider: "openrouter", model: "demo/cheap-model", cost_usd: 0.0003, cost_state: "known" }];
  if (body.force_route === "LOCAL_SIMPLE" || body.force_route === "LOCAL_RAG")
    return [route(body.force_route, "continuar localmente"), ...words("Sin internet: respondo solo con lo que hay en este equipo."), done()];
  if (m.includes("falla") || m.includes("error"))
    return [route("LOCAL_SIMPLE", "pregunta general"), { type: "error", code: "provider_unavailable", message: "Ollama no respondió a tiempo" }];
  if (m.includes("nube") || m.includes("actual"))
    return [route("CLOUD_CHEAP", "requiere información actual", "INTERNAL", { model_alias: "cloud-cheap" }), {
      type: "authorization_required", options: ["AUTHORIZE_ONCE", "CONTINUE_LOCAL", "CANCEL"],
      preview: { provider: "openrouter", recipients: ["openrouter.ai"], model: "demo/cheap-model", reason: "La pregunta pide datos actuales",
        privacy: "INTERNAL", fields: ["mensaje"], payload_preview: msg.slice(0, 200), payload_hash: "demo0000", estimated_cost_usd: 0.0004,
        ticket_request_id: "ticket-demo-1" } }];
  if (m.includes("tarea") || m.includes("guarda"))
    return [route("LOCAL_SIMPLE", "acción sobre tareas"),
      { type: "action", message: "Creé la tarea en Hoy.", event_id: 7, action: action("Crear tarea: Revisar VLAN de invitados", "done", "C1", 0),
        task: task("Revisar VLAN de invitados", { due_date: day(1), origin: "chat" }) },
      ...words("Listo: la dejé para mañana en **Hoy**. Puedes deshacerla desde aquí."), done()];
  return [route("LOCAL_RAG", "pregunta sobre tus documentos"),
    { type: "sources", sources: [
      { kind: "document", title: "manual-red-laboratorio-demo.pdf", location: "página 2", url: "/api/documents/doc-manual/file", privacy: "INTERNAL", verification: "unverified" },
      { kind: "document", title: "guia-dhcp-laboratorio-demo.md", location: "Reserva de direcciones", url: "/api/documents/doc-guia/file", privacy: "INTERNAL", verification: "unverified" }] },
    ...words("La red de invitados usa la **VLAN 30** y su arrendamiento DHCP dura **4 horas**.\n\nEl rango `192.168.10.1–192.168.10.49` queda reservado para infraestructura."),
    done()];
}

// ------------------------------------------------------------------ capture harness
// /__demo/harness hosts the app in a fixed-size iframe (viewport-exact frames even when the browser
// window can't be resized) and exposes helpers for driving states from DevTools/automation:
//   await load(1440, 900, "knowledge"); await click("Mapa"); cap("<captureId from generate_figma_design>")
const HARNESS = `<!doctype html><meta charset="utf-8"><title>Alice · arnés de captura</title>
<body style="margin:0;background:#111"><iframe id="f" style="border:0;display:block;width:1440px;height:900px"></iframe>
<script>
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const F = () => document.getElementById("f"), W = () => F().contentWindow;
const setMode = (q) => fetch("/__demo/set?" + q).then((r) => r.json());
async function load(w, h, hash, q = "mode=normal&auth=1") {
  await setMode(q); Object.assign(F().style, { width: w + "px", height: h + "px" });
  F().src = "/?r=" + Date.now() + "#" + hash; await sleep(3500);
  return { w: W().innerWidth, h: W().innerHeight, h1: W().document.querySelector("h1")?.textContent };
}
async function click(txt, sel = "button") {
  const b = [...W().document.querySelectorAll(sel)].find((x) => x.textContent.trim() === txt || x.getAttribute("aria-label") === txt);
  if (!b) return "no " + txt; b.click(); await sleep(1200); return "ok";
}
async function sendMessage(text) {
  const w = W(), d = w.document, ta = d.querySelector('textarea[aria-label="Mensaje"]');
  Object.getOwnPropertyDescriptor(w.HTMLTextAreaElement.prototype, "value").set.call(ta, text);
  ta.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(200);
  d.querySelector("form.composer").requestSubmit(); await sleep(2500); return "sent";
}
function cap(id) {
  window.last = "running";
  W().figma.captureForDesign({ captureId: id, endpoint: "https://mcp.figma.com/mcp/capture/" + id + "/submit?bindVariables=true", selector: "body" })
    .then(() => (window.last = "done"), (e) => (window.last = "err " + e));
  return "started";
}
</script>`;

// ------------------------------------------------------------------ plumbing
function send(res: ServerResponse, status: number, body: unknown, type = "application/json; charset=utf-8") {
  res.statusCode = status; res.setHeader("Content-Type", type);
  res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}
const readBody = (req: IncomingMessage) => new Promise<string>((ok, fail) => {
  let s = "";
  req.on("data", (c) => (s += c));
  req.on("end", () => ok(s));
  req.on("error", fail);
  req.on("aborted", () => fail(new Error("petición abortada")));
});
// 0.5 s of 8-bit mono silence at 8 kHz: a valid WAV so "Escuchar" plays without a TTS server.
function silentWav() {
  const n = 4000, b = Buffer.alloc(44 + n, 0x80);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(8000, 24); b.writeUInt32LE(8000, 28); b.writeUInt16LE(1, 32); b.writeUInt16LE(8, 34); b.write("data", 36); b.writeUInt32LE(n, 40);
  return b;
}

async function handle(req: IncomingMessage, res: ServerResponse) {
  const url = new URL(req.url!, "http://demo");
  const method = req.method!;
  const path = url.pathname;
  const raw = method === "GET" ? "" : await readBody(req);
  let body: any; try { body = raw ? JSON.parse(raw) : undefined; } catch { body = undefined; }

  if (!state.auth && path !== "/api/login") return send(res, 401, { detail: "Sesión no iniciada" });
  if (state.mode === "error" && ["/api/today", "/api/documents"].includes(path)) return send(res, 503, { detail: "El backend de demostración simula una caída" });

  if (method === "POST" && path === "/api/chat") {
    const r = state.contract ? chatV1(body) : { status: 200, events: chatScript(body?.message ?? "", body ?? {}) };
    if (r.status !== 200) return send(res, r.status, { detail: r.detail });
    res.setHeader("Content-Type", "application/x-ndjson");
    for (const ev of r.events!) { res.write(JSON.stringify(ev) + "\n"); await new Promise((ok) => setTimeout(ok, 25)); }
    return res.end();
  }
  const conv = path.match(/^\/api\/conversations\/([^/]+)$/);
  if (conv && method === "GET" && state.contract) {
    const c = convs.get(decodeURIComponent(conv[1]));
    return c ? send(res, 200, c) : send(res, 404, { detail: "Conversación no encontrada" });
  }
  const file = path.match(/^\/api\/documents\/([^/]+)\/file$/);
  if (file && files[file[1]]) return send(res, 200, readFileSync(resolve(SAMPLES, files[file[1]][0])), files[file[1]][1]);
  // Upload/voice: accepted without reading the payload (nothing real is stored or transcribed).
  if (method === "POST" && path === "/api/documents") {
    docs.push({ ...docs[0], document_id: nid("doc"), original_name: "archivo-subido-demo.pdf", status: "pending", chunks: null, ingested_at: iso() });
    return send(res, 201, { duplicate: false });
  }
  if (method === "POST" && path === "/api/voice/stt") return send(res, 200, { text: "¿Qué VLAN usa la red de invitados?" });
  if (method === "POST" && path === "/api/voice/tts") return send(res, 200, silentWav(), "audio/wav");
  if (method === "POST" && path === "/api/tasks") return send(res, 201, { task: task(body?.title ?? "Nueva tarea", body ?? {}), event_id: 9 });
  if (method === "PATCH" && path.startsWith("/api/tasks/")) return send(res, 200, { task: task("Actualizada", { ...body, task_id: path.split("/").pop() }), event_id: 10 });
  if (method === "POST" && /^\/api\/(events\/\d+\/undo|egress\/.+\/approve|documents\/.+\/cancel)$/.test(path)) return send(res, 200, { ok: true });
  if (method === "DELETE") return send(res, 200, { ok: true });

  const fn = routes[`${method} ${path}`];
  if (!fn) return send(res, 404, { detail: `Demo: sin fixture para ${method} ${path}` });
  try { return send(res, 200, fn(url.searchParams, body)); }
  catch (e) {
    if (Array.isArray(e)) return send(res, e[0], { detail: e[1] }); // fixtures throw [status, detail]
    return send(res, 500, { detail: String(e) });
  }
}

export function demoApi(): Plugin {
  return {
    name: "alice-demo-api",
    // Figma html-to-design capture: triggered manually with window.figma.captureForDesign(...) once the
    // screen is in the wanted state (the app owns location.hash, so the #figmacapture flow can't be used).
    transformIndexHtml: () => [{ tag: "script", attrs: { src: "https://mcp.figma.com/mcp/html-to-design/capture.js", async: true }, injectTo: "head" }],
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url!, "http://demo");
        if (url.pathname === "/__demo/harness") return send(res, 200, HARNESS, "text/html; charset=utf-8");
        if (url.pathname === "/__demo/set") {
          const mode = url.searchParams.get("mode"), auth = url.searchParams.get("auth");
          if (mode === "normal" || mode === "empty" || mode === "error") state.mode = mode;
          if (auth !== null) state.auth = auth === "1";
          const contract = url.searchParams.get("contract");
          if (contract !== null) state.contract = contract === "1";
          return send(res, 200, state);
        }
        if (!url.pathname.startsWith("/api/")) return next();
        handle(req, res).catch((e) => send(res, 500, { detail: String(e) }));
      });
    },
  };
}
