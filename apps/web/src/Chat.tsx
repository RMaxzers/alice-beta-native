import { useEffect, useMemo, useRef, useState } from "react";
import { api, errMsg, raw } from "./api";
import { Logo, type LogoState } from "./Logo";
import { renderMarkdown } from "./md";

export type Privacy = "PUBLIC" | "INTERNAL" | "PRIVATE";
const RANK: Record<Privacy, number> = { PUBLIC: 0, INTERNAL: 1, PRIVATE: 2 };
export const strictest = (...p: Privacy[]): Privacy => p.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), "PUBLIC" as Privacy);

type Source = { kind: string; title: string; location?: string | null; url?: string | null; privacy: Privacy; verification: string; retrieved_at?: string | null };
type Decision = { route: string; reason: string; decided_by: string; privacy: Privacy; model_alias?: string | null; confidence?: number | null };
type Tool = { name: string; summary: string; sql?: string; params?: unknown[] };
type Preview = {
  provider: string; recipients: string[]; model: string; reason: string; privacy: Privacy; fields: string[];
  payload_preview: string; payload_hash: string; estimated_cost_usd: number | null; ticket_request_id: string;
};
type Done = { request_id: string; provider: string | null; model: string | null; latency_s: number; queue_s: number; retrieval_s: number;
  tokens_out: number | null; cost_usd: number | null; cost_state: string; privacy: Privacy | null };
type Body = { message: string; privacy: Privacy; history: { role: string; content: string; privacy: Privacy }[];
  document_ids: string[]; force_route?: string; authorization_ticket?: string };
type Status = "streaming" | "done" | "error" | "cancelled" | "consent";
type Msg = {
  id: string; role: "user" | "assistant"; content: string; privacy: Privacy; status: Status;
  decision?: Decision; raisedBy?: string[]; tools: Tool[]; sources: Source[]; done?: Done; error?: string;
  consent?: { preview: Preview; options: string[]; body: Body }; estimate?: number | null; attachments?: string[];
};
type Doc = { document_id: string; original_name: string; privacy: Privacy; status: string; kind: string };

const LOGO_FOR_ROUTE: Record<string, LogoState> = {
  LOCAL_RAG: "knowledge", STRUCTURED_QUERY: "knowledge", LOG_ANALYSIS: "knowledge", OBSERVABILITY: "observability",
  CLOUD_CHEAP: "cloud", CLOUD_POWERFUL: "cloud", WEB_RESEARCH: "cloud", FINANCIAL_RESEARCH: "cloud",
};
const PRIV_HELP: Record<Privacy, string> = {
  PRIVATE: "No sale del equipo sin tu autorización explícita para ese envío.",
  INTERNAL: "Procesamiento local por defecto; salida solo con autorización puntual.",
  PUBLIC: "Apta para cloud/web si está habilitado y hay presupuesto. No rebaja adjuntos ni historial.",
};
const safeUrl = (u?: string | null) => !!u && /^(https?:\/\/|\/api\/documents\/)/i.test(u);
const uid = () => Math.random().toString(36).slice(2);

export function Chat({ setLogo }: { setLogo: (s: LogoState) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [privacy, setPrivacy] = useState<Privacy>("PRIVATE");
  const [docs, setDocs] = useState<Doc[]>([]);
  const [attached, setAttached] = useState<string[]>([]);
  const ctrl = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const busy = msgs.some((m) => m.status === "streaming");

  const loadDocs = () => api<Doc[]>("/api/documents").then((d) => setDocs(d.filter((x) => x.status === "ready"))).catch(() => setDocs([]));
  useEffect(() => { loadDocs(); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [msgs]);

  const patch = (id: string, f: (m: Msg) => Partial<Msg>) => setMsgs((ms) => ms.map((m) => (m.id === id ? { ...m, ...f(m) } : m)));

  const history = (upTo: Msg[]) =>
    upTo.filter((m) => m.status === "done" && m.content.trim()).slice(-20).map((m) => ({ role: m.role, content: m.content, privacy: m.privacy }));

  const attachedDocs = docs.filter((d) => attached.includes(d.document_id));
  const histPriv = history(msgs).map((h) => h.privacy);
  const effective = strictest(privacy, ...histPriv, ...attachedDocs.map((d) => d.privacy));
  const raisedBy = [
    ...(attachedDocs.some((d) => RANK[d.privacy] > RANK[privacy]) ? ["adjuntos"] : []),
    ...(histPriv.some((p) => RANK[p] > RANK[privacy]) ? ["historial"] : []),
  ];

  async function stream(id: string, body: Body) {
    const ac = new AbortController();
    ctrl.current = ac;
    setLogo("routing");
    patch(id, () => ({ status: "streaming", content: "", tools: [], sources: [], error: undefined, consent: undefined, done: undefined }));
    let final: Status = "done";
    try {
      const r = await raw("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ac.signal });
      const reader = r.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          const ev = JSON.parse(line);
          switch (ev.type) {
            case "route":
              setLogo(LOGO_FOR_ROUTE[ev.decision.route] ?? "local");
              patch(id, () => ({ decision: ev.decision, raisedBy: ev.raised_by, privacy: ev.decision.privacy }));
              break;
            case "tool": patch(id, (m) => ({ tools: [...m.tools, ev] })); break;
            case "sources": patch(id, (m) => ({ sources: [...m.sources, ...ev.sources] })); break;
            case "token": patch(id, (m) => ({ content: m.content + ev.text })); break;
            case "done": patch(id, (m) => ({ done: ev, privacy: ev.privacy ?? m.privacy })); break;
            case "authorization_required":
              final = "consent";
              patch(id, () => ({ consent: { preview: ev.preview, options: ev.options, body }, estimate: ev.preview.estimated_cost_usd }));
              break;
            case "error":
              final = "error";
              patch(id, () => ({ error: `${ev.message} (${ev.code})` }));
              break;
          }
        }
      }
    } catch (e) {
      if (ac.signal.aborted) final = "cancelled";
      else { final = "error"; patch(id, () => ({ error: errMsg(e) })); }
    }
    ctrl.current = null;
    patch(id, () => ({ status: final }));
    setLogo(final === "error" ? "error" : final === "consent" ? "cloud" : "idle");
  }

  function send(e?: React.FormEvent) {
    e?.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    const body: Body = { message, privacy, history: history(msgs), document_ids: attached };
    const aid = uid();
    setMsgs((ms) => [...ms,
      { id: uid(), role: "user", content: message, privacy, status: "done", tools: [], sources: [],
        attachments: attachedDocs.map((d) => d.original_name) },
      { id: aid, role: "assistant", content: "", privacy: effective, status: "streaming", tools: [], sources: [] }]);
    setText("");
    stream(aid, body);
  }

  async function authorize(m: Msg) {
    const c = m.consent!;
    try {
      await api(`/api/egress/${encodeURIComponent(c.preview.ticket_request_id)}/approve`, "POST");
    } catch (e) {
      patch(m.id, () => ({ status: "error", error: `No se pudo autorizar: ${errMsg(e)}`, consent: undefined }));
      return;
    }
    // Same message/history/route: the backend re-checks that the payload hash and destination match the ticket.
    stream(m.id, { ...c.body, authorization_ticket: c.preview.ticket_request_id, force_route: m.decision?.route });
  }

  function continueLocal(m: Msg) {
    const b = m.consent!.body;
    stream(m.id, { ...b, force_route: b.document_ids.length ? "LOCAL_RAG" : "LOCAL_SIMPLE" });
  }

  return (
    <section className="chat">
      <h1 className="sr-only">Chat</h1>
      <div className="msgs" role="log" aria-label="Conversación">
        <div className="thread">
        {msgs.length === 0 && (
          <div className="empty">
            <Logo size={88} />
            <h2>¿En qué te ayudo?</h2>
            <p>Las consultas se procesan en este equipo por defecto. Nada sale a un proveedor externo sin que lo autorices aquí.</p>
            <p className="muted">Puedes adjuntar documentos listos de Conocimiento, preguntar por el estado del sistema («¿cómo va la GPU?») o por tus tablas.</p>
          </div>
        )}
        {msgs.map((m) => m.role === "user" ? (
          <div key={m.id} className="msg user">
            <div className="bubble">{m.content}</div>
            <div className="meta"><PrivBadge p={m.privacy} />{m.attachments?.length ? <span className="muted"> · adjuntos: {m.attachments.join(", ")}</span> : null}</div>
          </div>
        ) : (
          <AssistantMsg key={m.id} m={m} onAuthorize={() => authorize(m)} onLocal={() => continueLocal(m)}
            onCancel={() => { patch(m.id, () => ({ status: "cancelled", consent: undefined })); setLogo("idle"); }} />
        ))}
        </div>
        <div ref={endRef} />
        <p className="sr-only" aria-live="polite">{busy ? "Alice está respondiendo" : msgs.length ? "Respuesta terminada" : ""}</p>
      </div>

      <form className="composer" onSubmit={send}>
        <div className="composer-box">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={20000} placeholder="Escribe tu consulta…"
            aria-label="Mensaje" onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <div className="composer-bar">
            <label className="inline">Privacidad
              <select value={privacy} onChange={(e) => setPrivacy(e.target.value as Privacy)} title={PRIV_HELP[privacy]}>
                <option value="PRIVATE">PRIVATE</option><option value="INTERNAL">INTERNAL</option><option value="PUBLIC">PUBLIC</option>
              </select>
            </label>
            <details className="attach">
              <summary>Adjuntos ({attached.length})</summary>
              <div className="pop">
                {docs.length === 0 ? <p className="muted">No hay documentos listos. Súbelos en Conocimiento.</p> :
                  docs.map((d) => (
                    <label key={d.document_id} className="check">
                      <input type="checkbox" checked={attached.includes(d.document_id)}
                        onChange={(e) => setAttached((a) => e.target.checked ? [...a, d.document_id] : a.filter((x) => x !== d.document_id))} />
                      {d.original_name} <PrivBadge p={d.privacy} />
                    </label>))}
                <button type="button" className="ghost small" onClick={loadDocs}>Actualizar lista</button>
              </div>
            </details>
            <span className="muted small-text">Efectiva: <PrivBadge p={effective} />
              {raisedBy.length > 0 && <> elevada por {raisedBy.join(" y ")}</>}</span>
            <span className="spacer" />
            {msgs.length > 0 && !busy && <button type="button" className="ghost small" onClick={() => { setMsgs([]); setLogo("idle"); }}>Nueva conversación</button>}
            {busy
              ? <button type="button" className="danger" onClick={() => ctrl.current?.abort()}>Cancelar</button>
              : <button className="primary" disabled={!text.trim()}>Enviar</button>}
          </div>
        </div>
        <p className="muted small-text composer-help">{PRIV_HELP[privacy]} · Intro envía, Mayús+Intro salto de línea.</p>
      </form>
    </section>
  );
}

export function PrivBadge({ p }: { p: Privacy | string }) {
  return <span className={`badge priv-${p}`}>{p}</span>;
}

function cost(m: Msg): string {
  const d = m.done;
  if (d?.cost_state === "local") return "0 USD (local)";
  if (d?.cost_usd != null) return `USD ${d.cost_usd.toFixed(5)} (conocido)`;
  if (m.estimate != null) return `≤ USD ${m.estimate.toFixed(5)} (estimado)` + (d ? "; real desconocido" : "");
  return d ? "desconocido" : "—";
}

function AssistantMsg({ m, onAuthorize, onLocal, onCancel }: { m: Msg; onAuthorize: () => void; onLocal: () => void; onCancel: () => void }) {
  const html = useMemo(() => renderMarkdown(m.content), [m.content]);
  const c = m.consent;
  return (
    <div className="msg assistant" data-route={m.decision ? LOGO_FOR_ROUTE[m.decision.route] ?? "local" : undefined}>
      <span className="avatar-ai" aria-hidden />
      <div className="msg-body">
      <div className="bubble">
        {m.content ? <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
          : m.status === "streaming" ? <span className="muted typing">{m.decision ? "Generando…" : "Decidiendo ruta…"}</span> : null}
        {m.status === "cancelled" && <p className="muted">Cancelado: no se generó más respuesta.</p>}
        {m.error && <p className="error" role="alert">{m.error}</p>}
        {c && m.status === "consent" && (
          <div className="consent" role="group" aria-label="Autorización de salida">
            <h3>Esta consulta necesita salir del equipo</h3>
            <p className="small-text">Revisa qué se enviará. Solo sale si pulsas «Autorizar una vez»; la autorización vale para este envío exacto.</p>
            <dl>
              <dt>Proveedor</dt><dd>{c.preview.provider}</dd>
              <dt>Destinatarios</dt><dd>{c.preview.recipients.join(", ") || "—"}</dd>
              <dt>Modelo</dt><dd>{c.preview.model}</dd>
              <dt>Motivo</dt><dd>{c.preview.reason}</dd>
              <dt>Privacidad</dt><dd><PrivBadge p={c.preview.privacy} /></dd>
              <dt>Qué sale</dt><dd>{c.preview.fields.join(", ")}</dd>
              <dt>Coste estimado</dt><dd>{c.preview.estimated_cost_usd == null ? "desconocido" : `≤ USD ${c.preview.estimated_cost_usd.toFixed(5)}`}</dd>
            </dl>
            <details><summary>Ver contenido exacto que saldrá</summary><pre className="payload">{c.preview.payload_preview}</pre>
              <p className="muted small-text">SHA-256: <code>{c.preview.payload_hash.slice(0, 16)}…</code> · autorización de un solo uso, caduca en 5 min</p></details>
            <div className="row wrap">
              {c.options.includes("AUTHORIZE_ONCE") && <button className="primary" onClick={onAuthorize}>Autorizar una vez</button>}
              {c.options.includes("CONTINUE_LOCAL") && <button onClick={onLocal}>Continuar localmente</button>}
              <button className="ghost" onClick={onCancel}>Cancelar</button>
            </div>
            {c.options.includes("CONTINUE_LOCAL") && <p className="muted small-text">Localmente no habrá datos actuales de internet ni modelo cloud.</p>}
          </div>
        )}
      </div>
      {(m.decision || m.done) && (
        <details className="details">
          <summary>
            <i className="route-dot" aria-hidden />{m.decision?.route ?? "—"} · {m.done?.provider ?? "…"}{m.done ? ` · ${m.done.latency_s}s` : ""} <PrivBadge p={m.privacy} />
          </summary>
          <dl>
            <dt>Ruta</dt><dd>{m.decision?.route} <span className="muted">({m.decision?.decided_by})</span></dd>
            <dt>Motivo</dt><dd>{m.decision?.reason}</dd>
            {m.raisedBy && m.raisedBy.length > 0 && <><dt>Privacidad</dt><dd>elevada por {m.raisedBy.join(" y ")}</dd></>}
            <dt>Proveedor</dt><dd>{m.done?.provider ?? "—"}</dd>
            <dt>Modelo</dt><dd>{m.done?.model ?? m.decision?.model_alias ?? "—"}</dd>
            <dt>Latencia</dt><dd>{m.done ? `${m.done.latency_s} s (cola ${m.done.queue_s} s, recuperación ${m.done.retrieval_s} s)` : "—"}</dd>
            {m.done?.tokens_out != null && <><dt>Tokens salida</dt><dd>{m.done.tokens_out}</dd></>}
            <dt>Coste</dt><dd>{cost(m)}</dd>
            {m.done && <><dt>Petición</dt><dd><code>{m.done.request_id}</code></dd></>}
          </dl>
          {m.tools.length > 0 && <><h4>Herramientas</h4><ul>{m.tools.map((t, i) => (
            <li key={i}><strong>{t.name}</strong>: {t.summary}{t.sql && <pre className="payload">{t.sql}{t.params?.length ? `\n-- params: ${JSON.stringify(t.params)}` : ""}</pre>}</li>))}</ul></>}
          {m.sources.length > 0 && <><h4>Fuentes</h4><ol>{m.sources.map((s, i) => (
            <li key={i}>
              {safeUrl(s.url) ? <a href={s.url!} target="_blank" rel="noopener noreferrer">{s.title}</a> : s.title}
              {s.location && <span className="muted"> — {s.location}</span>} <PrivBadge p={s.privacy} /> <span className="badge">{s.verification}</span>
            </li>))}</ol></>}
        </details>
      )}
      </div>
    </div>
  );
}
