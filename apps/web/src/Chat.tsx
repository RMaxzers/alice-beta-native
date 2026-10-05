import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, errMsg, raw } from "./api";
import { Logo, type LogoState } from "./Logo";
import { Orb } from "./Orb";
import { renderMarkdown } from "./md";
import { ACTION_STATUS_LABEL, type Action, type Priority, type Privacy, type Task } from "./tasks";
import {
  MIC_GENERIC_ERROR, MIC_PERMISSION_DENIED, MIC_UNAVAILABLE, fetchVoiceStatus, levelMeter, pickMimeType, synthesizeSpeech,
  toSpeechText, transcribeAudio, voiceSupported, type LevelMeter, type VoiceStatus,
} from "./voice";
import "./voice.css";

export type { Privacy };
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
  document_ids: string[]; force_route?: string; authorization_ticket?: string; conversation_id?: string; client_request_id?: string };
type Status = "streaming" | "done" | "error" | "cancelled" | "consent" | "interrupted";
// API contract v1 (alice-coordination/API_CONTRACT.md): server-side conversations and file actions.
type FileOp = {
  operation_id: string; tool: string; destination: string; executor_name: string; status: "running" | "done" | "failed" | "needs_review";
  verification: { verified: boolean; sha256: string; bytes: number } | null; error: string | null; created_at: string;
};
type ConvSummary = { conversation_id: string; title: string; privacy: Privacy; updated_at: string };
type StoredMsg = { message_id: string; role: "user" | "assistant"; content: string; privacy: Privacy; status: string;
  sources?: Source[]; operation_ids?: string[] };
type Identity = { api_contract: string; executor_name: string; file_action: { enabled: boolean; root_label: string } };
type ActionCard = { action: Action | FileOp | null; task: Task | null; event_id: number | null; message: string; undone?: boolean; undoError?: string };
const isFileOp = (a: Action | FileOp | null): a is FileOp => !!a && "operation_id" in a;
const FILE_OP_LABEL: Record<FileOp["status"], string> = {
  running: "En ejecución", done: "Resultado verificado", failed: "Error", needs_review: "Resultado desconocido: revisar",
};
type TaskSuggestion = { kind: "create_task"; title: string; description?: string; due_date?: string | null; priority?: Priority;
  sources?: { kind: "log"; document_id: string; line: number }[] };
type SuggestionCard = { suggestion: TaskSuggestion; note: string; state: "idle" | "creating" | "created" | "error";
  error?: string; createdTask?: Task; createdEventId?: number | null; duplicate?: boolean; undone?: boolean };
type Msg = {
  id: string; role: "user" | "assistant"; content: string; privacy: Privacy; status: Status;
  decision?: Decision; raisedBy?: string[]; tools: Tool[]; sources: Source[]; done?: Done; error?: string;
  consent?: { preview: Preview; options: string[]; body: Body }; estimate?: number | null; attachments?: string[];
  actions: ActionCard[]; suggestions: SuggestionCard[];
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
const STORED_NOTE: Record<string, string | undefined> = {
  failed: "Este turno terminó con error.",
  interrupted: "Turno interrumpido: revisa sus acciones antes de volver a pedirlo.",
  running: "Turno aún en curso en el servidor.",
  awaiting_authorization: "Quedó pendiente de autorización; vuelve a enviarlo para decidir.",
};
const safeUrl =(u?: string | null) => !!u && /^(https?:\/\/|\/api\/documents\/)/i.test(u);
const uid = () => Math.random().toString(36).slice(2);
type MicStatus = "idle" | "recording" | "transcribing";
type ListenState = { status: "idle" | "loading" | "playing" | "error"; error?: string };

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v4M9 22h6" />
    </svg>
  );
}

function SpeakerIcon({ muted }: { muted?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 9v6h4l5 4V5L8 9H4Z" />
      {muted ? <path d="M17 9l5 6M22 9l-5 6" /> : <path d="M17.5 8.5a5 5 0 0 1 0 7M20 6a8.5 8.5 0 0 1 0 12" />}
    </svg>
  );
}

export function Chat({ setLogo }: { setLogo: (s: LogoState) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [privacy, setPrivacy] = useState<Privacy>("PRIVATE");
  const [docs, setDocs] = useState<Doc[]>([]);
  const [attached, setAttached] = useState<string[]>([]);
  const ctrl = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const busy = msgs.some((m) => m.status === "streaming");
  const [streak, setStreak] = useState(0);

  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [micStatus, setMicStatus] = useState<MicStatus>("idle");
  const [micError, setMicError] = useState<string | null>(null);
  const micSupported = useMemo(voiceSupported, []);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [listen, setListen] = useState<Record<string, ListenState>>({});
  const playingRef = useRef<{ id: string; audio: HTMLAudioElement; url: string } | null>(null);
  // One live meter at a time (mic while recording, Alice's voice while playing) feeds the voice orb.
  const meterRef = useRef<LevelMeter | null>(null);
  const setMeter = (m: LevelMeter | null) => { meterRef.current?.close(); meterRef.current = m; };
  const voiceLevel = useCallback(() => meterRef.current?.level() ?? 0, []);

  // v1 backend (identity answers api_contract "1") keeps conversations server-side; older backends need `history`.
  const [identity, setIdentity] = useState<Identity | null>(null);
  const v1 = identity?.api_contract === "1";
  const [convId, setConvId] = useState<string | null>(null);
  const [convs, setConvs] = useState<ConvSummary[]>([]);
  const [ops, setOps] = useState<FileOp[]>([]);
  const [convErr, setConvErr] = useState("");

  const loadDocs = () => api<Doc[]>("/api/documents").then((d) => setDocs(d.filter((x) => x.status === "ready"))).catch(() => setDocs([]));
  useEffect(() => { loadDocs(); }, []);
  useEffect(() => { api<Identity>("/api/identity").then(setIdentity).catch(() => setIdentity(null)); }, []);
  const loadConvs = () => api<ConvSummary[]>("/api/conversations").then(setConvs).catch((e) => setConvErr(errMsg(e)));
  useEffect(() => { if (v1) loadConvs(); }, [v1]);
  useEffect(() => {
    if (!v1 || !convId) { setOps([]); return; }
    api<FileOp[]>(`/api/file-actions?conversation_id=${encodeURIComponent(convId)}`).then(setOps).catch(() => setOps([]));
  }, [v1, convId, busy]);

  async function openConversation(id: string) {
    setConvErr("");
    try {
      const q = encodeURIComponent(id);
      const [c, convOps] = await Promise.all([
        api<{ conversation_id: string; messages: StoredMsg[] }>(`/api/conversations/${q}`),
        api<FileOp[]>(`/api/file-actions?conversation_id=${q}&limit=200`).catch(() => [] as FileOp[]),
      ]);
      // Stored turns bring their sources and operation ids (R-03); route and timing are not stored, so no route chip.
      const opById = new Map(convOps.map((o) => [o.operation_id, o]));
      const out: Msg[] = [];
      c.messages.forEach((s, i) => {
        const note = STORED_NOTE[s.status];
        const actions: ActionCard[] = (s.operation_ids ?? []).flatMap((oid) => {
          const op = opById.get(oid);
          return op ? [{ action: op, task: null, event_id: null, message: s.content }] : [];
        });
        out.push({ id: s.message_id, role: s.role, content: actions.length ? "" : s.content, privacy: s.privacy,
          status: s.status === "complete" ? "done" : "interrupted",
          error: s.role === "assistant" ? note : undefined, tools: [], sources: s.sources ?? [], actions, suggestions: [] });
        // A turn that never produced an answer (interrupted, failed early, awaiting authorization) still gets a visible note.
        if (s.role === "user" && note && c.messages[i + 1]?.role !== "assistant")
          out.push({ id: s.message_id + "-note", role: "assistant", content: "", privacy: s.privacy, status: "interrupted", error: note,
            tools: [], sources: [], actions: [], suggestions: [] });
      });
      setMsgs(out);
      setConvId(c.conversation_id);
      setLogo("idle");
    } catch (e) { setConvErr(errMsg(e)); }
  }

  function newConversation() { setMsgs([]); setConvId(null); setLogo("idle"); }
  const [voiceErr, setVoiceErr] = useState(false);
  useEffect(() => { fetchVoiceStatus().then(setVoiceStatus).catch(() => setVoiceErr(true)); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [msgs]);
  useEffect(() => () => { playingRef.current?.audio.pause(); recorderRef.current?.stream.getTracks().forEach((t) => t.stop()); meterRef.current?.close(); }, []);

  async function startRecording() {
    setMicError(null);
    if (!micSupported) { setMicError(MIC_UNAVAILABLE); return; }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setMicError((e as DOMException)?.name === "NotAllowedError" ? MIC_PERMISSION_DENIED : MIC_GENERIC_ERROR);
      return;
    }
    const mime = pickMimeType();
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunksRef.current = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
    try { setMeter(levelMeter((ctx) => ctx.createMediaStreamSource(stream), false)); } catch { setMeter(null); }
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      setMeter(null);
      const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
      setMicStatus("transcribing");
      try {
        const heard = await transcribeAudio(blob);
        setText((t) => (t.trim() && heard ? `${t.trim()} ${heard}` : heard || t));
      } catch (e) {
        setMicError(errMsg(e));
      }
      setMicStatus("idle");
    };
    recorderRef.current = rec;
    rec.start();
    setMicStatus("recording");
  }

  function toggleMic() {
    if (micStatus === "recording") recorderRef.current?.stop();
    else if (micStatus === "idle") startRecording();
  }

  async function toggleListen(id: string, content: string) {
    const cur = playingRef.current;
    if (cur?.id === id) {
      cur.audio.pause();
      setMeter(null);
      URL.revokeObjectURL(cur.url);
      playingRef.current = null;
      setListen((s) => ({ ...s, [id]: { status: "idle" } }));
      return;
    }
    if (cur) {
      cur.audio.pause();
      URL.revokeObjectURL(cur.url);
      setListen((s) => ({ ...s, [cur.id]: { status: "idle" } }));
    }
    setListen((s) => ({ ...s, [id]: { status: "loading" } }));
    try {
      const blob = await synthesizeSpeech(toSpeechText(content));
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      // Without a meter the audio still plays normally; the orb then just breathes.
      try { setMeter(levelMeter((ctx) => ctx.createMediaElementSource(audio), true)); } catch { setMeter(null); }
      audio.onended = () => { setListen((s) => ({ ...s, [id]: { status: "idle" } })); URL.revokeObjectURL(url); playingRef.current = null; setMeter(null); };
      audio.onerror = () => {
        setListen((s) => ({ ...s, [id]: { status: "error", error: "No se pudo reproducir el audio." } }));
        URL.revokeObjectURL(url); playingRef.current = null; setMeter(null);
      };
      playingRef.current = { id, audio, url };
      await audio.play();
      setListen((s) => ({ ...s, [id]: { status: "playing" } }));
    } catch (e) {
      setListen((s) => ({ ...s, [id]: { status: "error", error: errMsg(e) } }));
    }
  }

  // Voice orb follows real availability (/api/voice/status + browser mic support):
  // slate = off/unavailable, violet = ready or thinking, cyan = hearing/speaking (reacting to the live level).
  const speaking = Object.values(listen).some((l) => l.status === "playing");
  const voiceActive = micStatus !== "idle" || speaking;
  const voiceOff = voiceErr || voiceStatus?.enabled === false || !micSupported;
  const voiceState = voiceOff ? "off" : !voiceStatus ? "checking" : micStatus === "recording" ? "recording"
    : micStatus === "transcribing" ? "transcribing" : speaking ? "speaking" : "ready";
  const VOICE_TEXT: Record<typeof voiceState, string> = {
    off: voiceErr ? "No pude comprobar la voz." : !micSupported ? "La voz necesita https o 127.0.0.1." : "Voz desactivada en este servidor.",
    checking: "Comprobando la voz…", ready: "Toca el orbe para hablar.", recording: "Te escucho. Toca para terminar.",
    transcribing: "Transcribiendo…", speaking: "Alice está hablando.",
  };
  const orbTint = voiceState === "off" ? "slate" : micStatus === "recording" || speaking ? "cyan" : "violet";
  const orbEnergy = voiceState === "off" ? 0.04 : micStatus === "recording" ? 0.8 : micStatus === "transcribing" ? 0.7 : speaking ? 0.5 : busy ? 0.45 : 0.15;
  // Keep the floating orb mounted briefly after voice ends so it can fade out.
  const [dock, setDock] = useState(false);
  useEffect(() => {
    if (voiceActive) { setDock(true); return; }
    const t = window.setTimeout(() => setDock(false), 450);
    return () => window.clearTimeout(t);
  }, [voiceActive]);
  const canTalk = !voiceOff && !!voiceStatus;
  const canListen = !voiceErr && voiceStatus?.enabled === true && voiceStatus.tts.reachable;

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

  async function stream(id: string, req: Body) {
    // Every POST is a new request for the server: a fresh idempotency key, also for the authorized/local retry
    // (reusing it with a different payload is a 409). The conversation id learned mid-stream is carried over.
    const body: Body = v1 ? { ...req, client_request_id: crypto.randomUUID(), ...(convId && !req.conversation_id ? { conversation_id: convId } : {}) } : req;
    const ac = new AbortController();
    ctrl.current = ac;
    setLogo("routing");
    patch(id, () => ({ status: "streaming", content: "", tools: [], sources: [], actions: [], suggestions: [], error: undefined, consent: undefined, done: undefined }));
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
            case "conversation":
              setConvId(ev.conversation_id);
              patch(id, (m) => ({ privacy: strictest(m.privacy, ev.privacy) }));
              break;
            case "route":
              setLogo(LOGO_FOR_ROUTE[ev.decision.route] ?? "local");
              patch(id, () => ({ decision: ev.decision, raisedBy: ev.raised_by, privacy: ev.decision.privacy }));
              break;
            case "tool": patch(id, (m) => ({ tools: [...m.tools, ev] })); break;
            case "sources": patch(id, (m) => ({ sources: [...m.sources, ...ev.sources] })); break;
            case "action":
              patch(id, (m) => ({ actions: [...m.actions, { action: ev.action, task: ev.task ?? null, event_id: ev.event_id ?? null, message: ev.message }] }));
              break;
            case "suggestion":
              patch(id, (m) => ({ suggestions: [...m.suggestions, { suggestion: ev.suggestion, note: ev.note, state: "idle" }] }));
              break;
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
    if (v1) loadConvs();
    setLogo(final === "error" ? "error" : final === "consent" ? "cloud" : "idle");
  }

  function send(e?: React.FormEvent) {
    e?.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setStreak((n) => n + 1);
    }
    const body: Body = v1
      ? { message, privacy, history: [], document_ids: attached, ...(convId ? { conversation_id: convId } : {}) }
      : { message, privacy, history: history(msgs), document_ids: attached };
    const aid = uid();
    setMsgs((ms) => [...ms,
      { id: uid(), role: "user", content: message, privacy, status: "done", tools: [], sources: [], actions: [], suggestions: [],
        attachments: attachedDocs.map((d) => d.original_name) },
      { id: aid, role: "assistant", content: "", privacy: effective, status: "streaming", tools: [], sources: [], actions: [], suggestions: [] }]);
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

  async function undoEvent(eventId: number): Promise<void> {
    await api(`/api/events/${eventId}/undo`, "POST");
  }

  async function undoAction(msgId: string, idx: number) {
    const a = msgs.find((m) => m.id === msgId)?.actions[idx];
    if (!a || a.event_id == null) return;
    try {
      await undoEvent(a.event_id);
      patch(msgId, (m) => ({ actions: m.actions.map((x, i) => (i === idx ? { ...x, undone: true } : x)) }));
    } catch (e) {
      patch(msgId, (m) => ({ actions: m.actions.map((x, i) => (i === idx ? { ...x, undoError: errMsg(e) } : x)) }));
    }
  }

  async function undoSuggestion(msgId: string, idx: number) {
    const s = msgs.find((m) => m.id === msgId)?.suggestions[idx];
    if (!s || s.createdEventId == null) return;
    try {
      await undoEvent(s.createdEventId);
      patch(msgId, (m) => ({ suggestions: m.suggestions.map((x, i) => (i === idx ? { ...x, undone: true } : x)) }));
    } catch (e) {
      patch(msgId, (m) => ({ suggestions: m.suggestions.map((x, i) => (i === idx ? { ...x, error: errMsg(e) } : x)) }));
    }
  }

  async function createFromSuggestion(msgId: string, idx: number) {
    const s = msgs.find((m) => m.id === msgId)?.suggestions[idx];
    if (!s) return;
    patch(msgId, (m) => ({ suggestions: m.suggestions.map((x, i) => (i === idx ? { ...x, state: "creating" } : x)) }));
    try {
      const key = crypto.randomUUID();
      const r = await raw("/api/tasks", {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({ title: s.suggestion.title, description: s.suggestion.description, due_date: s.suggestion.due_date,
          priority: s.suggestion.priority, kind: "work", sources: s.suggestion.sources }),
      });
      const body = await r.json() as { task: Task; action: Action; event_id: number; duplicate: boolean };
      patch(msgId, (m) => ({ suggestions: m.suggestions.map((x, i) => (i === idx
        ? { ...x, state: "created", createdTask: body.task, createdEventId: body.duplicate ? null : body.event_id, duplicate: body.duplicate }
        : x)) }));
    } catch (e) {
      patch(msgId, (m) => ({ suggestions: m.suggestions.map((x, i) => (i === idx ? { ...x, state: "error", error: errMsg(e) } : x)) }));
    }
  }

  return (
    <section className="chat">
      <h1 className="sr-only">Chat</h1>
      <div className="msgs" role="log" aria-label="Conversación">
        <div className="thread">
        {msgs.length === 0 && (
          <div className="empty">
            <button type="button" className="orb-btn" onClick={toggleMic} disabled={!canTalk || micStatus === "transcribing"}
              aria-pressed={micStatus === "recording"}
              aria-label={!canTalk ? VOICE_TEXT[voiceState] : micStatus === "recording" ? "Detener grabación" : "Hablar con Alice"}
              title={!micSupported ? MIC_UNAVAILABLE : undefined}>
              <Orb size={208} tint={orbTint} energy={orbEnergy} level={voiceLevel}>
                <Logo size={84} state={micStatus === "transcribing" ? "routing" : "idle"} />
              </Orb>
            </button>
            <p className={`voice-state voice-${voiceState}`} aria-live="polite">{VOICE_TEXT[voiceState]}</p>
            <h2>¿En qué te ayudo?</h2>
            <p className="muted">Se procesa en este equipo por defecto; nada sale sin tu autorización.</p>
          </div>
        )}
        {msgs.map((m) => m.role === "user" ? (
          <div key={m.id} className="msg user">
            <div className="bubble">{m.content}</div>
            <div className="meta"><PrivBadge p={m.privacy} />{m.attachments?.length ? <span className="muted"> · adjuntos: {m.attachments.join(", ")}</span> : null}</div>
          </div>
        ) : (
          <AssistantMsg key={m.id} m={m} onAuthorize={() => authorize(m)} onLocal={() => continueLocal(m)}
            onCancel={() => { patch(m.id, () => ({ status: "cancelled", consent: undefined })); setLogo("idle"); }}
            onUndoAction={(i) => undoAction(m.id, i)} onCreateSuggestion={(i) => createFromSuggestion(m.id, i)}
            onUndoSuggestion={(i) => undoSuggestion(m.id, i)}
            listen={listen[m.id] ?? { status: "idle" }} voiceEnabled={canListen}
            onToggleListen={() => toggleListen(m.id, m.content)} />
        ))}
        </div>
        <div ref={endRef} />
        <p className="sr-only" aria-live="polite">{busy ? "Alice está respondiendo" : msgs.length ? "Respuesta terminada" : ""}</p>
      </div>

      {dock && msgs.length > 0 && (
        <div className={`voice-dock${voiceActive ? "" : " is-leaving"}`} aria-hidden="true">
          <Orb size={112} tint={orbTint} energy={orbEnergy} level={voiceLevel} dimCenter={false} />
        </div>
      )}
      <form className="composer" onSubmit={send}>
        <div className="composer-box">
          {streak > 0 && <span key={streak} className="send-streak" aria-hidden onAnimationEnd={() => setStreak(0)} />}
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={20000} placeholder="Escribe tu consulta…"
            aria-label="Mensaje" onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <div className="composer-bar">
            {canTalk && (
              <button type="button" className={`mic-btn${micStatus === "recording" ? " is-recording" : ""}`}
                aria-pressed={micStatus === "recording"} disabled={micStatus === "transcribing" || !micSupported}
                title={!micSupported ? MIC_UNAVAILABLE : micStatus === "recording" ? "Detener grabación" : "Grabar un mensaje de voz"}
                onClick={toggleMic}>
                <MicIcon />
                <span className="sr-only">{micStatus === "recording" ? "Detener grabación" : "Grabar un mensaje de voz"}</span>
              </button>
            )}
            {micStatus === "transcribing" && <span className="muted small-text">Transcribiendo…</span>}
            {micError && <span className="error small-text" role="alert">{micError}</span>}
            <label className="inline">Privacidad
              <select value={privacy} onChange={(e) => setPrivacy(e.target.value as Privacy)} title={PRIV_HELP[privacy]}>
                <option value="PRIVATE">PRIVATE</option><option value="INTERNAL">INTERNAL</option><option value="PUBLIC">PUBLIC</option>
              </select>
            </label>
            <details className="attach" name="composer-pop">
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
            {v1 && (
              <details className="attach" name="composer-pop" onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) loadConvs(); }}>
                <summary>Conversaciones ({convs.length})</summary>
                <div className="pop conv-list">
                  {convErr && <p className="error small-text" role="alert">{convErr}</p>}
                  {convs.length === 0 ? <p className="muted">Aún no hay conversaciones guardadas.</p> :
                    <ul>{convs.map((c) => (
                      <li key={c.conversation_id}>
                        <button type="button" className={`ghost small${c.conversation_id === convId ? " is-active" : ""}`} disabled={busy}
                          aria-current={c.conversation_id === convId ? "true" : undefined} onClick={(e) => { e.currentTarget.closest("details")?.removeAttribute("open"); openConversation(c.conversation_id); }}>
                          {c.title}
                        </button> <PrivBadge p={c.privacy} /> <span className="muted small-text">{new Date(c.updated_at).toLocaleString("es-ES")}</span>
                      </li>))}</ul>}
                </div>
              </details>
            )}
            {v1 && convId && (
              <details className="attach" name="composer-pop">
                <summary>Acciones ({ops.length})</summary>
                <div className="pop op-list">
                  <p className="muted small-text">Equipo ejecutor: <strong>{identity?.executor_name}</strong>
                    {identity && !identity.file_action.enabled && " · carpeta autorizada sin configurar"}</p>
                  {ops.length === 0 ? <p className="muted">Esta conversación no tiene acciones sobre archivos.</p> :
                    ops.map((op) => <FileOpCard key={op.operation_id} op={op} />)}
                </div>
              </details>
            )}
            <span className="muted small-text">Efectiva: <PrivBadge p={effective} />
              {raisedBy.length > 0 && <> elevada por {raisedBy.join(" y ")}</>}</span>
            <span className="spacer" />
            {msgs.length > 0 && !busy && <button type="button" className="ghost small" onClick={newConversation}>Nueva conversación</button>}
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

function FileOpCard({ op, message }: { op: FileOp; message?: string }) {
  const tone = op.status === "done" ? "ok" : op.status === "failed" ? "danger" : op.status === "needs_review" ? "warn" : "muted";
  return (
    <div className={`chat-card chat-card-${tone}`} role={op.status === "failed" ? "alert" : "status"}>
      <p><strong>{FILE_OP_LABEL[op.status]}:</strong> {message || op.error || op.destination}</p>
      <dl className="op-facts small-text">
        <dt>Destino</dt><dd><code>{op.destination}</code></dd>
        <dt>Equipo</dt><dd>{op.executor_name}</dd>
        {op.verification && <><dt>Comprobación</dt><dd>
          {op.verification.verified ? "contenido releído y coincide" : "no coincide"} · {op.verification.bytes} B · SHA-256 <code>{op.verification.sha256.slice(0, 12)}…</code></dd></>}
        {op.error && op.status !== "failed" && <><dt>Detalle</dt><dd>{op.error}</dd></>}
        <dt>Operación</dt><dd><code>{op.operation_id}</code></dd>
      </dl>
      {op.status === "needs_review" && <p className="muted small-text">No se sabe si el archivo quedó bien. No repitas la petición sin revisar la carpeta.</p>}
    </div>
  );
}

function ActionResultCard({ a, onUndo }: { a: ActionCard; onUndo: () => void }) {
  if (isFileOp(a.action)) return <FileOpCard op={a.action} message={a.message} />;
  const task = a.task;
  const when = task ? `${task.title}${task.due_date ? ` · ${task.due_date}` : ""}` : null;
  const canUndo = !a.undone && a.event_id != null;
  const undoRow = (
    <div className="row wrap">
      {canUndo && <button type="button" className="ghost small" onClick={onUndo}>Deshacer</button>}
      {a.undone && <span className="muted small-text">Deshecho</span>}
      {a.undoError && <span className="error small-text">{a.undoError}</span>}
      <a className="button small" href="#today">Ver en Hoy</a>
    </div>
  );
  // action can be null (e.g. the task already existed): show the backend's message and the task, no status inference.
  if (!a.action) {
    return <div className="chat-card chat-card-muted"><p>{a.message}</p>{when && <p className="muted small-text">{when}</p>}{undoRow}</div>;
  }
  const st = a.action.status;
  if (st === "done" && task?.status === "draft") {
    return (
      <div className="chat-card chat-card-warn">
        <p><strong>Borrador guardado (no es una tarea activa):</strong> {a.message}</p>
        {when && <p className="muted small-text">{when}</p>}
        {undoRow}
      </div>
    );
  }
  if (st === "done") {
    return (
      <div className="chat-card chat-card-ok" role="status">
        <p><strong>Hecho:</strong> {a.message}</p>
        {when && <p className="muted small-text">{when}</p>}
        {undoRow}
      </div>
    );
  }
  if (st === "proposed") return <div className="chat-card chat-card-muted"><p><strong>Borrador / propuesta, no ejecutada.</strong> {a.message}</p></div>;
  if (st === "failed") return <div className="chat-card chat-card-danger" role="alert"><p className="error"><strong>Fallido:</strong> {a.message}</p></div>;
  if (st === "needs_review" || st === "awaiting_authorization")
    return <div className="chat-card chat-card-warn"><p><strong>Requiere tu revisión: no se ejecutó.</strong> {a.message}</p></div>;
  return <div className="chat-card chat-card-muted"><p><strong>{ACTION_STATUS_LABEL[st]}:</strong> {a.message}</p></div>;
}

function SuggestionResultCard({ s, onCreate, onUndo }: { s: SuggestionCard; onCreate: () => void; onUndo: () => void }) {
  return (
    <div className="chat-card chat-card-muted">
      <p><strong>Sugerencia (no se ha creado nada):</strong> {s.suggestion.title}</p>
      {s.note && <p className="muted small-text">{s.note}</p>}
      {s.state === "idle" && <button type="button" className="small" onClick={onCreate}>Crear seguimiento</button>}
      {s.state === "creating" && <p className="muted small-text">Creando…</p>}
      {s.state === "created" && (
        <div className="row wrap">
          <p className="ok-text small-text">
            {s.duplicate ? "Ya existía una tarea igual" : "Creada"}{s.createdTask ? `: ${s.createdTask.title}` : ""}
          </p>
          {!s.duplicate && !s.undone && s.createdEventId != null && <button type="button" className="ghost small" onClick={onUndo}>Deshacer</button>}
          {s.undone && <span className="muted small-text">Deshecho</span>}
          <a className="button small" href="#today">Ver en Hoy</a>
        </div>
      )}
      {s.state === "error" && <p className="error small-text" role="alert">{s.error}</p>}
    </div>
  );
}

function AssistantMsg({ m, onAuthorize, onLocal, onCancel, onUndoAction, onCreateSuggestion, onUndoSuggestion, listen, voiceEnabled, onToggleListen }: {
  m: Msg; onAuthorize: () => void; onLocal: () => void; onCancel: () => void;
  onUndoAction: (idx: number) => void; onCreateSuggestion: (idx: number) => void; onUndoSuggestion: (idx: number) => void;
  listen: ListenState; voiceEnabled: boolean; onToggleListen: () => void;
}) {
  const html = useMemo(() => renderMarkdown(m.content), [m.content]);
  const c = m.consent;
  const logoState: LogoState = m.decision ? LOGO_FOR_ROUTE[m.decision.route] ?? "local" : "idle";
  return (
    <div className="msg assistant" data-route={m.decision ? LOGO_FOR_ROUTE[m.decision.route] ?? "local" : undefined} data-status={m.status}>
      <span className="avatar-ai" aria-hidden="true"><Logo size={28} state={logoState} /></span>
      <div className="msg-body">
      <div className="bubble">
        {m.content ? <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
          : m.status === "streaming" ? <span className="muted typing">{m.decision ? "Generando…" : "Decidiendo ruta…"}</span> : null}
        {m.status === "done" && m.content.trim() && voiceEnabled && (
          <div className="listen-row">
            <button type="button" className={`ghost small listen-btn${listen.status === "playing" ? " is-active" : ""}`}
              aria-pressed={listen.status === "playing"} disabled={listen.status === "loading"} onClick={onToggleListen}>
              <SpeakerIcon muted={listen.status === "playing"} />
              {listen.status === "loading" ? "Cargando…" : listen.status === "playing" ? "Detener" : "Escuchar"}
            </button>
            {listen.status === "error" && <span className="error small-text" role="alert">{listen.error}</span>}
          </div>
        )}
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
        {m.actions.map((a, i) => <ActionResultCard key={i} a={a} onUndo={() => onUndoAction(i)} />)}
        {m.suggestions.map((s, i) => (
          <SuggestionResultCard key={i} s={s} onCreate={() => onCreateSuggestion(i)} onUndo={() => onUndoSuggestion(i)} />
        ))}
      </div>
      {m.decision && (
        <details className="details">
          <summary>
            <i className="route-dot" aria-hidden />{m.decision.route} · {m.done?.provider ?? "…"}{m.done?.latency_s != null ? ` · ${m.done.latency_s}s` : ""} <PrivBadge p={m.privacy} />
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
