import { useEffect, useRef, useState } from "react";
import { api, errMsg, fmtBytes, fmtTime, getCsrf, unauthorized } from "./api";
import { PrivBadge, type Privacy } from "./Chat";
import { PageHead } from "./pages";

type Doc = {
  document_id: string; original_name: string; size_bytes: number; kind: string; ingested_at: string; privacy: Privacy;
  verification: string; status: "pending" | "processing" | "ready" | "failed"; status_detail: string | null; chunks: number | null; version: number;
};
type Upload = { id: string; name: string; pct: number; state: "uploading" | "done" | "error"; msg?: string };

const ACCEPT = ".pdf,.md,.markdown,.txt,.log,.csv,.xlsx";
const STATUS_ES = { pending: "en cola", processing: "procesando", ready: "listo", failed: "fallido" } as const;

function uploadFile(file: File, privacy: Privacy, onPct: (p: number) => void): Promise<{ duplicate: boolean }> {
  // XHR instead of fetch: fetch has no upload progress events.
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/api/documents");
    x.setRequestHeader("X-CSRF-Token", getCsrf());
    x.upload.onprogress = (e) => e.lengthComputable && onPct(Math.round((e.loaded / e.total) * 100));
    x.onload = () => {
      let body: { detail?: unknown; duplicate?: boolean } = {};
      try { body = JSON.parse(x.responseText); } catch { /* non-JSON */ }
      if (x.status === 401) unauthorized();
      if (x.status >= 200 && x.status < 300) resolve({ duplicate: !!body.duplicate });
      else reject(new Error(typeof body.detail === "string" ? body.detail : `HTTP ${x.status}`));
    };
    x.onerror = () => reject(new Error("Error de red durante la subida"));
    const fd = new FormData();
    fd.append("file", file);
    fd.append("privacy", privacy);
    x.send(fd);
  });
}

export function Knowledge() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [err, setErr] = useState("");
  const [privacy, setPrivacy] = useState<Privacy>("PRIVATE");
  const [maxMb, setMaxMb] = useState(50);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [q, setQ] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => api<Doc[]>("/api/documents").then((d) => { setDocs(d); setErr(""); }).catch((e) => setErr(errMsg(e)));
  useEffect(() => {
    load();
    api<{ max_upload_mb: number }>("/api/settings").then((s) => setMaxMb(s.max_upload_mb)).catch(() => {});
  }, []);
  // Poll while anything is still in flight.
  const busy = docs?.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [busy]);

  async function onFiles(files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      const id = Math.random().toString(36).slice(2);
      const up = (p: Partial<Upload>) => setUploads((u) => u.map((x) => (x.id === id ? { ...x, ...p } : x)));
      setUploads((u) => [{ id, name: f.name, pct: 0, state: "uploading" as const }, ...u].slice(0, 8));
      if (f.size > maxMb * 1024 * 1024) { up({ state: "error", msg: `Supera el límite de ${maxMb} MB (${fmtBytes(f.size)})` }); continue; }
      try {
        const r = await uploadFile(f, privacy, (pct) => up({ pct }));
        up({ state: "done", pct: 100, msg: r.duplicate ? "Ya existía (mismo contenido): no se duplica" : "Subido; procesando…" });
      } catch (e) { up({ state: "error", msg: errMsg(e) }); }
      load();
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  async function act(fn: () => Promise<unknown>) {
    try { await fn(); } catch (e) { setErr(errMsg(e)); }
    load();
  }

  const shown = (docs ?? []).filter((d) => d.original_name.toLowerCase().includes(q.toLowerCase()));

  return (
    <section className="page">
      <PageHead title="Conocimiento" sub="Documentos que Alice puede consultar. Todo se indexa en este equipo." />
      <div className="card">
        <h2>Subir documentos</h2>
        <p className="muted">PDF, Markdown, TXT, LOG, CSV o XLSX, hasta {maxMb} MB. Todo se procesa en este equipo. La privacidad elegida se aplica al documento y a todo lo que se derive de él.</p>
        <div className="row wrap">
          <label className="inline">Privacidad
            <select value={privacy} onChange={(e) => setPrivacy(e.target.value as Privacy)}>
              <option>PRIVATE</option><option>INTERNAL</option><option>PUBLIC</option>
            </select>
          </label>
          <input ref={fileRef} type="file" multiple accept={ACCEPT} onChange={(e) => onFiles(e.target.files)} aria-label="Elegir archivos" />
        </div>
        {uploads.length > 0 && <ul className="uploads">{uploads.map((u) => (
          <li key={u.id} className={u.state}>
            <span>{u.name}</span>
            {u.state === "uploading" ? <progress max={100} value={u.pct} aria-label={`Subiendo ${u.name}`} /> : null}
            <span className={u.state === "error" ? "error" : "muted"}>{u.state === "uploading" ? `${u.pct}%` : u.msg}</span>
          </li>))}</ul>}
      </div>

      <div className="card">
        <div className="row wrap between">
          <h2>Catálogo {docs && <span className="muted">({docs.length})</span>}</h2>
          <input type="search" placeholder="Buscar por nombre…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar documentos" />
        </div>
        {err && <p className="error" role="alert">{err}</p>}
        {docs === null ? <p className="muted">Cargando…</p>
          : docs.length === 0 ? <p className="muted">Aún no hay documentos. Sube uno arriba para poder hacer preguntas sobre él en el chat.</p>
          : shown.length === 0 ? <p className="muted">Ningún documento coincide con «{q}».</p>
          : <div className="table-wrap"><table>
            <thead><tr><th>Nombre</th><th>Tipo</th><th>Tamaño</th><th>Privacidad</th><th>Estado</th><th>Subido</th><th></th></tr></thead>
            <tbody>{shown.map((d) => (
              <tr key={d.document_id}>
                <td><a href={`/api/documents/${d.document_id}/file`} target="_blank" rel="noopener noreferrer">{d.original_name}</a>
                  {d.version > 1 && <span className="muted"> v{d.version}</span>}</td>
                <td>{d.kind}</td>
                <td>{fmtBytes(d.size_bytes)}</td>
                <td><PrivBadge p={d.privacy} /> <span className="badge">{d.verification}</span></td>
                <td><span className={`status st-${d.status}`}>{STATUS_ES[d.status] ?? d.status}</span>
                  {d.status_detail && <div className="muted small-text">{d.status_detail}</div>}</td>
                <td className="nowrap">{fmtTime(d.ingested_at)}</td>
                <td className="nowrap">
                  {(d.status === "pending" || d.status === "processing") &&
                    <button className="ghost small" onClick={() => act(() => api(`/api/documents/${d.document_id}/cancel`, "POST"))}>Cancelar</button>}
                  {confirm === d.document_id ? (
                    <span className="confirm" role="group" aria-label="Confirmar eliminación">
                      ¿Eliminar «{d.original_name}»? Se borran el original, sus fragmentos y vectores. No se puede deshacer.{" "}
                      <button className="danger small" onClick={() => { setConfirm(null); act(() => api(`/api/documents/${d.document_id}`, "DELETE")); }}>Eliminar documento</button>
                      <button className="ghost small" onClick={() => setConfirm(null)}>Conservar</button>
                    </span>
                  ) : <button className="ghost small" onClick={() => setConfirm(d.document_id)} aria-label={`Eliminar ${d.original_name}`}>Eliminar</button>}
                </td>
              </tr>))}
            </tbody></table></div>}
      </div>
    </section>
  );
}
