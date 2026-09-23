import { useLayoutEffect, useRef, useState } from "react";
import { animate, createTimeline, stagger } from "animejs";
import { api, errMsg, setCsrf } from "../api";
import { Logo } from "../Logo";
import { ARCH_LINKS, ARCH_NODES, WorldMap, reducedMotion, type Tone } from "./WorldMap";
import "./landing.css";

const FEATURES: [Tone, string, string][] = [
  ["local", "Local primero", "Las consultas se resuelven con modelos que corren en este PC. Por defecto, nada sale del equipo."],
  ["knowledge", "Conocimiento con citas", "Cuando responde con tus documentos, indica de qué archivo sale cada dato."],
  ["obs", "Observabilidad real", "CPU, GPU, modelos y cada consulta, medidos en este equipo. Si falta un dato, lo dice."],
  ["cloud", "Nube bajo consentimiento", "Antes de enviar datos privados a OpenRouter, te muestra qué sale y adónde, y espera tu permiso."],
];

const MAP_LABEL = "Mapa de dónde se procesan las consultas: este PC en Santiago (aproximado); enlace a OpenRouter en EE. UU. " +
  "solo con tu autorización; búsqueda web en Tavily sin ubicación fija; laptop remoto por red privada, ubicación desconocida.";

export function Landing({ onDone }: { onDone: (user: string) => void }) {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await api<{ user: string; csrf: string }>("/api/login", "POST", { username, password });
      setCsrf(r.csrf); setP(""); onDone(r.user);
    } catch (e) { setErr(errMsg(e)); } finally { setBusy(false); }
  }

  // Intro: orb entrance, staggered copy, login card, then feature cards. The map runs its own draw-in.
  useLayoutEffect(() => {
    if (reducedMotion() || !root.current) return;
    const $ = (s: string) => root.current!.querySelectorAll(s);
    const orb = animate($(".lp-brand svg"), { scale: [0.3, 1], rotate: [-90, 0], opacity: [0, 1], duration: 1100, ease: "outElastic(1, .7)" });
    const tl = createTimeline({ defaults: { ease: "outCubic", duration: 700 } })
      .add($(".lp-reveal"), { opacity: [0, 1], y: [18, 0], delay: stagger(90) }, 150)
      .add($(".lp-login"), { opacity: [0, 1], y: [24, 0] }, 350)
      .add($(".lp-map"), { opacity: [0, 1] }, 300)
      .add($(".lp-card"), { opacity: [0, 1], y: [20, 0], delay: stagger(110) }, 1300);
    return () => { orb.revert(); tl.revert(); };
  }, []);

  return (
    <div className="lp" ref={root}>
      <main className="lp-wrap">
        <section className="lp-hero" aria-labelledby="lp-title">
          <div className="lp-brand"><Logo size={56} /><strong className="lp-reveal">Alice</strong></div>
          <p className="lp-eyebrow lp-reveal">IA privada · corre en tu PC</p>
          <h1 id="lp-title" className="lp-reveal">Tu IA, en tu propio equipo.</h1>
          <p className="lp-lead lp-reveal">
            Alice responde con modelos locales y con tus documentos, en este PC.
            <b> Tus datos privados solo salen a la nube si tú lo autorizas</b>, en cada envío.
          </p>
        </section>

        <form className="lp-login" onSubmit={submit} aria-labelledby="lp-login-title">
          <h2 id="lp-login-title">Entrar a Alice</h2>
          <label>Usuario<input autoComplete="username" value={username} onChange={(e) => setU(e.target.value)} required /></label>
          <label>Contraseña<input type="password" autoComplete="current-password" value={password} onChange={(e) => setP(e.target.value)} required /></label>
          {err && <p className="error" role="alert">{err}</p>}
          <button className="primary" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
        </form>

        <section className="lp-map" aria-labelledby="lp-map-title">
          <h2 id="lp-map-title" className="sr-only">Dónde se procesa cada consulta</h2>
          <WorldMap nodes={ARCH_NODES} links={ARCH_LINKS} label={MAP_LABEL} intro />
          <p className="lp-cap">Arquitectura de Alice, no tráfico en vivo. Ubicaciones aproximadas; el laptop remoto no se ubica en el mapa.</p>
        </section>

        <ul className="lp-feat" aria-label="Qué hace Alice">
          {FEATURES.map(([tone, title, body]) => (
            <li key={title} className="lp-card" data-tone={tone}><h3>{title}</h3><p>{body}</p></li>
          ))}
        </ul>
      </main>
    </div>
  );
}
