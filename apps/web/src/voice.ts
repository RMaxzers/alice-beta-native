// Voice: browser-side helpers for the mic (speech-to-text) and "Escuchar" (text-to-speech) features.
// Both endpoints are same-origin (/api/voice/*) and proxy to services that never leave this machine.
import { raw, api } from "./api";
import { renderMarkdown } from "./md";

export type VoiceStatus = { enabled: boolean; tts: { reachable: boolean }; stt: { model: string; device: string; loaded: boolean } };

const TTS_MAX_CHARS = 2000;

export function voiceSupported(): boolean {
  return window.isSecureContext && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
}

// MediaRecorder's supported mime types vary by browser; let it pick a default if none of these match.
export function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"];
  return candidates.find((t) => MediaRecorder.isTypeSupported?.(t)) ?? "";
}

export const MIC_UNAVAILABLE = "El micrófono necesita una conexión segura (https) o http://127.0.0.1; no está disponible aquí.";
export const MIC_PERMISSION_DENIED = "Permiso de micrófono denegado: actívalo en los ajustes del navegador.";
export const MIC_GENERIC_ERROR = "No se pudo acceder al micrófono.";

export function fetchVoiceStatus(): Promise<VoiceStatus> {
  return api<VoiceStatus>("/api/voice/status");
}

export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("audio", blob, blob.type.includes("ogg") ? "grabacion.ogg" : "grabacion.webm");
  const r = await raw("/api/voice/stt", { method: "POST", body: form });
  const body = (await r.json()) as { text: string };
  return body.text;
}

export async function synthesizeSpeech(text: string, voice?: string): Promise<Blob> {
  const r = await raw("/api/voice/tts", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(voice ? { text, voice } : { text }),
  });
  return r.blob();
}

// Strip markdown/code before sending to TTS: reuses the same sanitized renderer as the chat bubble, then
// drops code blocks entirely (nothing to usefully read aloud) and takes plain text.
export function toSpeechText(markdown: string): string {
  const doc = new DOMParser().parseFromString(renderMarkdown(markdown), "text/html");
  doc.querySelectorAll("pre, code").forEach((el) => el.remove());
  return (doc.body.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, TTS_MAX_CHARS);
}

// Live 0..1 loudness for the voice orb. `toSpeakers` must be true for a media element (createMediaElementSource
// reroutes its audio through the graph); false for the mic so it is not echoed back.
export type LevelMeter = { level: () => number; close: () => void };
export function levelMeter(source: (ctx: AudioContext) => AudioNode, toSpeakers: boolean): LevelMeter {
  const ctx = new AudioContext();
  const an = ctx.createAnalyser();
  an.fftSize = 512;
  source(ctx).connect(an);
  if (toSpeakers) an.connect(ctx.destination);
  void ctx.resume();
  const buf = new Uint8Array(an.fftSize);
  return {
    level: () => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      return Math.min(1, Math.sqrt(sum / buf.length) * 4);
    },
    close: () => { void ctx.close(); },
  };
}
