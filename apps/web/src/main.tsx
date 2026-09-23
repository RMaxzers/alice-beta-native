import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, setCsrf, setOnUnauthorized } from "./api";
import { Logo, LogoState, STATE_LABEL } from "./Logo";
import { Chat } from "./Chat";
import { Knowledge } from "./Knowledge";
import { Observability } from "./Observability";
import { Models, SettingsPage, SystemPage } from "./pages";
import { Landing } from "./landing/Landing";
import { LiveMap } from "./landing/LiveMap";
import "./theme.css";
import "./styles.css";

const TABS = [
  ["home", "Inicio"], ["chat", "Chat"], ["knowledge", "Conocimiento"], ["observability", "Observabilidad"],
  ["models", "Modelos"], ["system", "Sistema"], ["settings", "Ajustes"],
] as const;

// 24px stroke icons (inline: CSP forbids remote assets).
const ICON: Record<string, string> = {
  home: "M3 11.5 12 4l9 7.5M5.5 9.5V20h13V9.5M10 20v-5h4v5",
  chat: "M4 5h16v11H9l-5 4V5Z M8 9.5h8 M8 12.5h5",
  knowledge: "M5 4h10l4 4v12H5V4Z M14 4v5h5 M8.5 13h7 M8.5 16.5h5",
  observability: "M3 20h18 M6 16v-4 M10.5 16V7 M15 16v-6 M19.5 16V4",
  models: "M12 3 20 7.5v9L12 21l-8-4.5v-9L12 3Z M4 7.5l8 4.5 8-4.5 M12 12v9",
  system: "M4 5h16v10H4z M9 19h6 M12 15v4 M7.5 10h2l1.5-2.5 2 5 1.5-2.5h2",
  settings: "M4 7h10 M18 7h2 M4 17h4 M12 17h8 M16 5v4 M10 15v4",
};
const Icon = ({ k }: { k: string }) => (
  <svg className="icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d={ICON[k]} /></svg>
);
type Tab = (typeof TABS)[number][0];


function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined); // undefined = checking
  const [tab, setTab] = useState<Tab>(() => (TABS.some(([k]) => "#" + k === location.hash) ? location.hash.slice(1) as Tab : "home"));
  const [logo, setLogo] = useState<LogoState>("idle");
  const [localOnly, setLocalOnly] = useState<boolean | null>(null);

  useEffect(() => {
    setOnUnauthorized(() => { setCsrf(""); setUser(null); });
    api<{ user: string; csrf: string }>("/api/session")
      .then((s) => { setCsrf(s.csrf); setUser(s.user); })
      .catch(() => setUser(null));
  }, []);
  useEffect(() => { history.replaceState(null, "", "#" + tab); }, [tab]);
  // Re-read on tab change so the badge follows a toggle made in Ajustes.
  useEffect(() => {
    if (!user) return;
    api<{ local_only: boolean }>("/api/settings").then((s) => setLocalOnly(s.local_only)).catch(() => setLocalOnly(null));
  }, [user, tab]);

  const logout = useCallback(async () => {
    try { await api("/api/logout", "POST"); } catch { /* session may already be gone */ }
    setCsrf(""); setUser(null);
  }, []);

  if (user === undefined) return <main className="login"><Logo size={72} state="routing" /></main>;
  if (user === null) return <Landing onDone={setUser} />;

  return (
    <div className="shell">
      <a className="skip" href="#main">Saltar al contenido</a>
      <header className="topbar">
        <div className="brand" title={STATE_LABEL[logo]}>
          <Logo state={logo} size={36} />
          <div><strong>Alice</strong><small aria-live="polite">{STATE_LABEL[logo]}</small></div>
        </div>
        <div className="top-meta">
          {localOnly !== null && (
            <span className={`pill ${localOnly ? "pill-ok" : "pill-warn"}`} title={localOnly ? "El backend bloquea todo envío a proveedores externos" : "Puede salir contenido con tu autorización"}>
              <i aria-hidden /> {localOnly ? "Solo local" : "Salida autorizable"}
            </span>)}
          <div className="who"><span className="avatar" aria-hidden>{user.slice(0, 1).toUpperCase()}</span><span className="who-name">{user}</span>
            <button className="ghost small" onClick={logout}>Salir</button></div>
        </div>
      </header>
      <nav className="side" aria-label="Secciones">
        {TABS.map(([k, label]) => (
          <button key={k} className={tab === k ? "active" : ""} aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>
            <Icon k={k} /><span>{label}</span>
          </button>
        ))}
      </nav>
      <main className="content" id="main" tabIndex={-1}>
        {tab === "home" && <div className="page"><LiveMap /></div>}
        {/* Chat stays mounted so a conversation or stream survives tab switches. */}
        <div hidden={tab !== "chat"} className="fill"><Chat setLogo={setLogo} /></div>
        {tab === "knowledge" && <Knowledge />}
        {tab === "observability" && <Observability />}
        {tab === "models" && <Models />}
        {tab === "system" && <SystemPage />}
        {tab === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
