// Thin fetch wrapper: same-origin cookie session + CSRF header on state-changing requests.
let csrf = "";
let onUnauthorized: () => void = () => {};

export const setCsrf = (t: string) => { csrf = t; };
export const getCsrf = () => csrf;
export const setOnUnauthorized = (f: () => void) => { onUnauthorized = f; };
export const unauthorized = () => onUnauthorized();

export class HttpError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function detail(r: Response): Promise<string> {
  try {
    const j = await r.json();
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch { /* not JSON */ }
  return `HTTP ${r.status}`;
}

export async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD") headers.set("X-CSRF-Token", csrf);
  const r = await fetch(path, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  if (r.status === 401 && path !== "/api/login" && path !== "/api/session") onUnauthorized();
  if (!r.ok) throw new HttpError(r.status, await detail(r));
  return r;
}

export async function api<T = unknown>(path: string, method = "GET", json?: unknown, signal?: AbortSignal): Promise<T> {
  const r = await raw(path, {
    method, signal,
    headers: json === undefined ? undefined : { "Content-Type": "application/json" },
    body: json === undefined ? undefined : JSON.stringify(json),
  });
  return r.json() as Promise<T>;
}

export const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

// ---- formatting helpers shared by pages
export function fmtBytes(b: number | null | undefined): string {
  if (b == null) return "sin datos";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, v = b;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i ? 1 : 0)} ${u[i]}`;
}

export function fmtValue(v: number | null | undefined, unit: string): string {
  if (v == null || Number.isNaN(v)) return "sin datos";
  if (unit === "bytes") return fmtBytes(v);
  if (unit === "bytes/s") return fmtBytes(v) + "/s";
  const n = Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toPrecision(2);
  return `${n} ${unit}`;
}

export function fmtAge(s: number | null | undefined): string {
  if (s == null) return "sin datos";
  if (s < 60) return `hace ${Math.round(s)} s`;
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  return `hace ${(s / 3600).toFixed(1)} h`;
}

export const fmtTime = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("es-ES") : "—");
