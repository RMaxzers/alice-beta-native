import { useEffect, useState } from "react";
import { errMsg } from "./api";
import { BLOCKER_TEXT, blocker, currentSubscription, disablePush, enablePush, fetchPushConfig, type PushConfig } from "./push";

// One switch for this device. States: checking → off / on / blocked (with the reason and what to do).
export function DevicePush() {
  const [cfg, setCfg] = useState<PushConfig | null>(null);
  const [cfgErr, setCfgErr] = useState(false);
  const [on, setOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    fetchPushConfig().then(setCfg).catch(() => setCfgErr(true));
    currentSubscription().then((s) => setOn(!!s)).catch(() => setOn(false));
  }, []);

  const why = cfgErr ? "server-off" : blocker(cfg);
  const block = why && !(why === "denied" && on) ? BLOCKER_TEXT[why] : null;

  async function toggle() {
    setBusy(true); setErr(""); setMsg("");
    try {
      if (on) { await disablePush(); setOn(false); setMsg("Notificaciones desactivadas en este dispositivo."); }
      else if ((await enablePush(cfg!)) === "denied") setErr(BLOCKER_TEXT.denied.title + " " + BLOCKER_TEXT.denied.hint);
      else { setOn(true); setMsg("Listo. Te avisaré aquí aunque Alice esté cerrada."); }
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }
  return (
    <div className="device-push" aria-labelledby="dp-title">
      <div className="device-push-row">
        <div>
          <h2 id="dp-title">Notificaciones en este dispositivo</h2>
          <p className="muted small-text">
            {block ? block.title : on == null || (!cfg && !cfgErr) ? "Comprobando…" : on ? "Activadas." : "Desactivadas. Los avisos siguen apareciendo dentro de Alice."}
          </p>
        </div>
        {!block && on != null && cfg && (
          <button type="button" role="switch" aria-checked={on} aria-label="Notificaciones en este dispositivo" className={`switch${on ? " is-on" : ""}`} disabled={busy} onClick={toggle}>
            <span className="switch-knob" aria-hidden="true" /><span className="switch-text">{busy ? "…" : on ? "Sí" : "No"}</span>
          </button>
        )}
      </div>
      {block && <p className="small-text hint">{block.hint}</p>}
      {on && !block && <p className="muted small-text">Para probar, crea una tarea con aviso dentro de unos minutos.</p>}
      {msg && <p className="ok-text small-text" role="status">{msg}</p>}
      {err && <p className="error small-text" role="alert">{err}</p>}
    </div>
  );
}
