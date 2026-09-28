// Detail panel shared by the Órbita and Mapa views: same fields, same actions, same delete
// confirmation as the Lista table — just presented next to the visualization instead of in a row.
// Also owns two opt-in extras: a read-only Univer spreadsheet viewer for csv/xlsx documents, and an
// "Enviar a NotebookLM" action that mirrors the chat's egress-consent card (preview -> authorize once).
import { useEffect, useState } from "react";
import { PrivBadge, type Privacy } from "../Chat";
import { api, errMsg, fmtBytes, fmtTime } from "../api";
import { GROUP_LABEL, STATUS_ES, kindGroup, type Doc } from "./shared";
import { SpreadsheetViewer } from "./SpreadsheetViewer";

export interface Neighbor { id: string; name: string; similarity: number }

interface NBStatus { enabled: boolean; installed?: boolean; logged_in?: boolean; detail?: string }
interface NBPreview {
  recipients: string[]; privacy: Privacy; fields: string[]; ticket_request_id: string; how_to_revert: string;
  document?: { name: string; size_bytes: number };
}

function NotebookLMAction({ doc }: { doc: Doc }) {
  const [status, setStatus] = useState<NBStatus | null>(null);
  const [notebook, setNotebook] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState("");
  const [preview, setPreview] = useState<NBPreview | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<NBStatus>("/api/integrations/notebooklm/status").then((s) => !cancelled && setStatus(s)).catch(() => !cancelled && setStatus({ enabled: false }));
    return () => { cancelled = true; };
  }, []);
  // Switching documents must not carry over another document's pending authorization.
  useEffect(() => { setPreview(null); setErr(""); setResult(""); setNotebook(""); }, [doc.document_id]);

  if (!status?.enabled) return null;

  async function askPreview() {
    if (!notebook.trim()) return;
    setBusy(true); setErr(""); setResult("");
    try {
      setPreview(await api<NBPreview>("/api/integrations/notebooklm/preview", "POST", { document_id: doc.document_id, notebook: notebook.trim() }));
    } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  }

  async function authorize() {
    if (!preview) return;
    setBusy(true); setErr("");
    try {
      await api(`/api/egress/${encodeURIComponent(preview.ticket_request_id)}/approve`, "POST");
      await api("/api/integrations/notebooklm/send", "POST", { ticket_id: preview.ticket_request_id });
      setResult("Fuente añadida a NotebookLM.");
      setPreview(null); setNotebook("");
    } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  }

  return (
    <div className="doc-detail-notebooklm">
      <h4>NotebookLM</h4>
      {!status.installed || !status.logged_in ? (
        <p className="muted small-text">{status.detail}</p>
      ) : preview ? (
        <div className="consent" role="group" aria-label="Autorización de envío a NotebookLM">
          <h3>Este envío sale del equipo</h3>
          <p className="small-text">Revisa qué se enviará. Solo sale si pulsas «Autorizar una vez»; la autorización vale para este envío exacto.</p>
          <dl>
            <dt>Destino</dt><dd>{preview.recipients.join(", ") || "—"}</dd>
            <dt>Documento</dt><dd>{preview.document?.name}{preview.document && ` (${fmtBytes(preview.document.size_bytes)})`}</dd>
            <dt>Privacidad</dt><dd><PrivBadge p={preview.privacy} /></dd>
            <dt>Qué sale</dt><dd>{preview.fields.join(", ")}</dd>
            <dt>Cómo revertir</dt><dd>{preview.how_to_revert}</dd>
          </dl>
          <div className="row wrap">
            <button className="primary" disabled={busy} onClick={authorize}>Autorizar una vez</button>
            <button className="ghost" disabled={busy} onClick={() => setPreview(null)}>Cancelar</button>
          </div>
        </div>
      ) : (
        <div className="row wrap">
          <input value={notebook} onChange={(e) => setNotebook(e.target.value)} placeholder="Título o ID del notebook de NotebookLM"
                aria-label="Notebook de destino en NotebookLM" />
          <button className="ghost small" disabled={busy || !notebook.trim()} onClick={askPreview}>Enviar a NotebookLM</button>
        </div>
      )}
      {err && <p className="error" role="alert">{err}</p>}
      {result && <p className="muted small-text">{result}</p>}
    </div>
  );
}

export function DocDetail({
  doc, confirming, onAskDelete, onConfirmDelete, onCancelDelete, onCancelProcessing, onClose, neighbors, onSelectNeighbor,
}: {
  doc: Doc;
  confirming: boolean;
  onAskDelete: () => void;
  onConfirmDelete: () => void;
  onCancelDelete: () => void;
  onCancelProcessing: () => void;
  onClose?: () => void;
  neighbors?: Neighbor[];
  onSelectNeighbor?: (id: string) => void;
}) {
  const [sheetOpen, setSheetOpen] = useState(false);
  useEffect(() => setSheetOpen(false), [doc.document_id]);
  const isSheet = kindGroup(doc.kind) === "hojas";

  return (
    <aside className="doc-detail" aria-label={`Detalle de ${doc.original_name}`}>
      <div className="doc-detail-head">
        <h3>{doc.original_name}{doc.version > 1 && <span className="muted"> v{doc.version}</span>}</h3>
        {onClose && <button className="ghost small" onClick={onClose} aria-label="Cerrar detalle">Cerrar</button>}
      </div>
      <dl className="kv">
        <dt>Tipo</dt><dd>{GROUP_LABEL[kindGroup(doc.kind)]} <span className="muted small-text">({doc.kind})</span></dd>
        <dt>Tamaño</dt><dd>{fmtBytes(doc.size_bytes)}</dd>
        <dt>Subido</dt><dd>{fmtTime(doc.ingested_at)}</dd>
        <dt>Privacidad</dt><dd><PrivBadge p={doc.privacy} /> <span className="badge">{doc.verification}</span></dd>
        <dt>Estado</dt><dd><span className={`status st-${doc.status}`}>{STATUS_ES[doc.status] ?? doc.status}</span>
          {doc.status_detail && <div className="muted small-text">{doc.status_detail}</div>}</dd>
        <dt>Fragmentos</dt><dd>{doc.chunks ?? "—"}</dd>
      </dl>
      <div className="row wrap doc-detail-actions">
        <a className="button small" href={`/api/documents/${doc.document_id}/file`} target="_blank" rel="noopener noreferrer">Ver o descargar</a>
        {isSheet && doc.status === "ready" && <button className="ghost small" onClick={() => setSheetOpen(true)}>Abrir planilla</button>}
        {(doc.status === "pending" || doc.status === "processing") &&
          <button className="ghost small" onClick={onCancelProcessing}>Cancelar</button>}
        {confirming ? (
          <span className="confirm" role="group" aria-label="Confirmar eliminación">
            ¿Eliminar «{doc.original_name}»? Se borran el original, sus fragmentos y vectores. No se puede deshacer.{" "}
            <button className="danger small" onClick={onConfirmDelete}>Eliminar documento</button>
            <button className="ghost small" onClick={onCancelDelete}>Conservar</button>
          </span>
        ) : <button className="ghost small" onClick={onAskDelete}>Eliminar</button>}
      </div>
      {neighbors && (
        <div className="doc-detail-neighbors">
          <h4>Documentos relacionados</h4>
          {neighbors.length === 0
            ? <p className="muted small-text">Sin relaciones por encima del umbral de similitud.</p>
            : <ul>{neighbors.map((n) => (
                <li key={n.id}>
                  <button className="ghost small" onClick={() => onSelectNeighbor?.(n.id)}>{n.name}</button>{" "}
                  <span className="muted small-text">{Math.round(n.similarity * 100)}% de similitud</span>
                </li>))}</ul>}
        </div>
      )}
      <NotebookLMAction doc={doc} />
      {sheetOpen && <SpreadsheetViewer doc={doc} onClose={() => setSheetOpen(false)} />}
    </aside>
  );
}
