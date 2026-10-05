// Web Push on this device: the browser side of the backend push API (alice-coordination/API_CONTRACT.md, etapa 2).
import { api } from "./api";

export type PushConfig = { enabled: boolean; vapid_public_key: string | null; reason?: string | null };
// Why push can't be turned on here, as one short sentence plus what to do.
export type Blocker = "insecure" | "unsupported" | "ios-install" | "denied" | "server-off";

export const BLOCKER_TEXT: Record<Blocker, { title: string; hint: string }> = {
  insecure: { title: "Necesita una conexión segura (HTTPS).", hint: "Abre Alice con la dirección https de Tailscale o desde este PC en 127.0.0.1." },
  unsupported: { title: "Este navegador no admite notificaciones push.", hint: "Usa Chrome, Edge, Firefox o Safari reciente." },
  "ios-install": { title: "En iPhone, primero añade Alice a la pantalla de inicio.", hint: "Compartir → «Añadir a pantalla de inicio», y ábrela desde ese icono." },
  denied: { title: "Bloqueaste las notificaciones para Alice.", hint: "Permítelas en los ajustes del sitio del navegador (icono junto a la dirección) y vuelve aquí." },
  "server-off": { title: "El servidor de Alice no tiene las notificaciones activadas.", hint: "Los avisos siguen apareciendo dentro de Alice." },
};

const isIOS = () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const standalone = () => matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;

export function blocker(cfg: PushConfig | null): Blocker | null {
  if (!window.isSecureContext) return "insecure";
  if (isIOS() && !standalone()) return "ios-install";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  if (cfg && (!cfg.enabled || !cfg.vapid_public_key)) return "server-off";
  return null;
}

const b64ToBytes = (s: string) => {
  const b = atob((s + "=".repeat((4 - (s.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
};

const registration = () => navigator.serviceWorker.register("/sw.js", { scope: "/" });

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return (await reg?.pushManager.getSubscription()) ?? null;
}

export const fetchPushConfig = () => api<PushConfig>("/api/push/config");

const deviceLabel = () => {
  const ua = navigator.userAgent;
  const os = /Android/.test(ua) ? "Android" : isIOS() ? "iPhone/iPad" : /Windows/.test(ua) ? "Windows" : /Mac/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "Dispositivo";
  const br = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "navegador";
  return `${br} en ${os}`;
};

// Returns "denied" when the user dismisses or blocks the permission prompt.
export async function enablePush(cfg: PushConfig): Promise<"ok" | "denied"> {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return "denied";
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const key = b64ToBytes(cfg.vapid_public_key!);
  let sub = await reg.pushManager.getSubscription();
  // A subscription made with another server key can't receive our pushes: replace it.
  const old = sub?.options.applicationServerKey;
  if (sub && old && new Uint8Array(old).join() !== key.join()) { await sub.unsubscribe(); sub = null; }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await api("/api/push/subscriptions", "POST", { ...sub.toJSON(), device_label: deviceLabel() });
  return "ok";
}

export async function disablePush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  // Tell the server first so it stops sending even if the browser unsubscribe fails.
  await api("/api/push/subscriptions", "DELETE", { endpoint: sub.endpoint });
  await sub.unsubscribe();
}

