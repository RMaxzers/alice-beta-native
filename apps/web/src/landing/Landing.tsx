import { useLayoutEffect, useRef, useState } from "react";
import { animate, createTimeline, stagger } from "animejs";
import { api, errMsg, setCsrf } from "../api";
import { Logo } from "../Logo";
import { reducedMotion } from "./Network";
import { Portal } from "./Portal";
import "./landing.css";

export function Landing({ onDone }: { onDone: (user: string) => void }) {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [boostKey, setBoostKey] = useState(0);
  const [errorKey, setErrorKey] = useState(0);
  const root = useRef<HTMLDivElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(""); setBoostKey((k) => k + 1);
    try {
      const r = await api<{ user: string; csrf: string }>("/api/login", "POST", { username, password });
      setCsrf(r.csrf); setP(""); onDone(r.user);
    } catch (e) { setErr(errMsg(e)); setErrorKey((k) => k + 1); } finally { setBusy(false); }
  }

  // Intro: brand + copy stagger in, the login card settles, the portal fades up. One orchestrated
  // entrance only; the portal's own ambient motion continues quietly afterward.
  useLayoutEffect(() => {
    if (reducedMotion() || !root.current) return;
    const $ = (s: string) => root.current!.querySelectorAll(s);
    const orb = animate($(".lp-brand svg"), { scale: [0.3, 1], rotate: [-90, 0], opacity: [0, 1], duration: 1100, ease: "outElastic(1, .7)" });
    const tl = createTimeline({ defaults: { ease: "outCubic", duration: 700 } })
      .add($(".lp-reveal"), { opacity: [0, 1], y: [16, 0], delay: stagger(90) }, 150)
      .add($(".lp-login"), { opacity: [0, 1], y: [22, 0] }, 380)
      .add($(".lp-portal"), { opacity: [0, 1], scale: [0.92, 1] }, 250);
    return () => { orb.revert(); tl.revert(); };
  }, []);

  const logoState = err ? "error" : busy ? "routing" : "idle";

  return (
    <div className="lp" ref={root}>
      <main className="lp-wrap">
        <section className="lp-hero" aria-labelledby="lp-title">
          <div className="lp-brand"><Logo size={40} /><strong className="lp-reveal">Alice</strong></div>
          <h1 id="lp-title" className="lp-reveal">Tu IA, en tu propio equipo.</h1>
          <p className="lp-lead lp-reveal">
            Alice responde con modelos locales y con tus documentos, en este PC. Tus datos privados
            solo salen a la nube si tú lo autorizas, en cada envío.
          </p>

          <form className="lp-login lp-reveal" onSubmit={submit} aria-labelledby="lp-login-title">
            <h2 id="lp-login-title">Entrar a Alice</h2>
            <label>Usuario<input autoComplete="username" value={username} onChange={(e) => setU(e.target.value)} required /></label>
            <label>Contraseña<input type="password" autoComplete="current-password" value={password} onChange={(e) => setP(e.target.value)} required /></label>
            {err && <p className="error" role="alert">{err}</p>}
            <button className="primary" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
            <p className="lp-note">Acceso privado por Tailscale: solo tus propios dispositivos llegan a este equipo.</p>
          </form>
        </section>

        <Portal state={logoState} boostKey={boostKey} errorKey={errorKey} />
      </main>
    </div>
  );
}
