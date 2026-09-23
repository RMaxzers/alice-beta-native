import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, errMsg, setCsrf, setOnUnauthorized } from "./api";
import { Logo, LogoState, STATE_LABEL } from "./Logo";
import { Chat } from "./Chat";
import { Knowledge } from "./Knowledge";
import { Observability } from "./Observability";
import { Models, SettingsPage, SystemPage } from "./pages";
import "./styles.css";

const TABS = [
  ["chat", "Chat"], ["knowledge", "Knowledge"], ["observability", "Observability"],
  ["models", "Models"], ["system", "System"], ["settings", "Settings"],
] as const;
type Tab = (typeof TABS)[number][0];

function Login({ onDone }: { onDone: (u: string) => void }) {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await api<{ user: string; csrf: string }>("/api/login", "POST", { username, password });
      setCsrf(r.csrf); setP(""); onDone(r.user);
    } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  }
  return (
    <main className="login">
      <form onSubmit={submit} className="card">
        <div className="brand big"><Logo size={72} /><h1>Alice</h1></div>
        <label>Usuario<input autoComplete="username" value={username} onChange={(e) => setU(e.target.value)} required /></label>
        <label>Contraseña<input type="password" autoComplete="current-password" value={password} onChange={(e) => setP(e.target.value)} required /></label>
        {err && <p className="error" role="alert">{err}</p>}
        <button className="primary" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
      </form>
    </main>
  );
}

function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined); // undefined = checking
  const [tab, setTab] = useState<Tab>(() => (TABS.some(([k]) => "#" + k === location.hash) ? location.hash.slice(1) as Tab : "chat"));
  const [logo, setLogo] = useState<LogoState>("idle");

  useEffect(() => {
    setOnUnauthorized(() => { setCsrf(""); setUser(null); });
    api<{ user: string; csrf: string }>("/api/session")
      .then((s) => { setCsrf(s.csrf); setUser(s.user); })
      .catch(() => setUser(null));
  }, []);
  useEffect(() => { history.replaceState(null, "", "#" + tab); }, [tab]);

  const logout = useCallback(async () => {
    try { await api("/api/logout", "POST"); } catch { /* session may already be gone */ }
    setCsrf(""); setUser(null);
  }, []);

  if (user === undefined) return <main className="login"><Logo size={72} state="routing" /></main>;
  if (user === null) return <Login onDone={setUser} />;

  return (
    <div className="shell">
      <header className="side">
        <div className="brand" title={STATE_LABEL[logo]}>
          <Logo state={logo} size={44} />
          <div><strong>Alice</strong><small aria-live="polite">{STATE_LABEL[logo]}</small></div>
        </div>
        <nav aria-label="Secciones">
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? "active" : ""} aria-current={tab === k ? "page" : undefined} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <div className="who"><span>{user}</span><button className="ghost" onClick={logout}>Salir</button></div>
      </header>
      <main className="content">
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
