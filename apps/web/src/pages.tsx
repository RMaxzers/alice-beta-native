import { Fragment, type ReactNode, useEffect, useState } from "react";
import { api, errMsg, fmtBytes, fmtTime } from "./api";

export type Health = { state: string; detail: string; checked_at?: string };
const TONE: Record<string, string> = {
  healthy: "ok", degraded: "warn", configured_not_tested: "warn", not_configured: "warn", unavailable: "bad", error: "bad", disabled: "off",
};
const STATE_ES: Record<string, string> = {
  healthy: "operativo", degraded: "degradado", configured_not_tested: "configurado, sin probar", not_configured: "sin configurar",
  unavailable: "no disponible", error: "error", disabled: "deshabilitado",
};

export function PageHead({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
      {children && <div className="actions">{children}</div>}
    </header>
  );
}

export function HealthGrid({ health, compact }: { health: Record<string, Health>; compact?: boolean }) {
  return (
    <ul className={`health ${compact ? "compact" : ""}`}>
      {Object.entries(health).map(([k, h]) => (
        <li key={k} className={`tone-${TONE[h.state] ?? "warn"}`}>
          <span className="dot" aria-hidden />
          <strong>{k}</strong> <span className="state">{STATE_ES[h.state] ?? h.state}</span>
          {!compact && <p className="muted small-text">{h.detail}</p>}
        </li>))}
    </ul>
  );
}

function useLoad<T>(path: string): [T | null, string, () => void] {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState("");
  const load = () => api<T>(path).then((x) => { setD(x); setErr(""); }).catch((e) => setErr(errMsg(e)));
  useEffect(() => { load(); }, [path]);
  return [d, err, load];
}

// ------------------------------------------------------------------ Models
type Alias = {
  alias: string; provider: string; model: string; location: string; available: boolean; loaded?: boolean;
  vram_bytes?: number | null; size_bytes?: number | null; state?: string; detail?: string;
  pricing?: { usd_per_mtok_in: number; usd_per_mtok_out: number } | null;
};
type ModelsResp = { ollama_reachable: boolean; aliases: Alias[]; routes: Record<string, string>; future_providers: Record<string, string> };

export function Models() {
  const [d, err, load] = useLoad<ModelsResp>("/api/models");
  return (
    <section className="page">
      <PageHead title="Modelos" sub="Alias, dónde se ejecuta cada modelo y cuánto cuesta."><button className="ghost small" onClick={load}>Actualizar</button></PageHead>
      {err && <p className="error" role="alert">{err}</p>}
      {!d ? !err && <p className="muted">Cargando…</p> : <>
        {!d.ollama_reachable && <p className="error">Ollama no responde: los modelos locales aparecen como no disponibles. Comprueba el servicio Ollama en Sistema.</p>}
        <div className="card table-wrap"><table>
          <thead><tr><th>Alias</th><th>Proveedor / modelo</th><th>Ubicación</th><th>Disponible</th><th>Carga</th><th>Precio (USD/Mtok)</th></tr></thead>
          <tbody>{d.aliases.map((a) => (
            <tr key={a.alias}>
              <td><strong>{a.alias}</strong><div className="muted small-text">{Object.entries(d.routes).filter(([, v]) => v === a.alias).map(([r]) => r).join(", ")}</div></td>
              <td>{a.provider}<div className="muted small-text"><code>{a.model}</code></div></td>
              <td>{a.location}</td>
              <td>{a.available ? <span className="status st-ready">sí</span> : <span className="status st-failed">no</span>}
                {a.detail && <div className="muted small-text">{a.detail}</div>}</td>
              <td>{a.provider === "ollama" ? (a.loaded ? `cargado · VRAM ${fmtBytes(a.vram_bytes)}` : "no cargado") +
                (a.size_bytes ? ` · ${fmtBytes(a.size_bytes)} en disco` : "") : "—"}</td>
              <td>{a.pricing ? `${a.pricing.usd_per_mtok_in.toFixed(2)} in / ${a.pricing.usd_per_mtok_out.toFixed(2)} out` : a.provider === "ollama" ? "local" : "desconocido"}</td>
            </tr>))}
          </tbody></table></div>
        <div className="card">
          <h2>Proveedores futuros</h2>
          <ul>{Object.entries(d.future_providers).map(([k, v]) => (
            <li key={k}>{k}: {v === "DISABLED" ? "deshabilitado (sin clave en .env)" : "clave presente, pendiente de integrar"}</li>))}</ul>
        </div>
      </>}
    </section>
  );
}

// ------------------------------------------------------------------ System
type SystemResp = {
  health: Record<string, Health>; local_only: boolean; version: string; grafana_local: string;
  budget: { per_request_usd: number; daily_usd: number; today: { accounted: number; reserved_open: number; unknown_cost_calls: number } };
  remote: { public_origin: string | null; via_proxy: boolean };
};

export function SystemPage() {
  const [d, err, load] = useLoad<SystemResp>("/api/system");
  const checked = d && Object.values(d.health)[0]?.checked_at;
  return (
    <section className="page">
      <PageHead title="Sistema" sub="Estado del equipo, presupuesto y dependencias."><button className="ghost small" onClick={load}>Comprobar ahora</button></PageHead>
      {err && <p className="error" role="alert">{err}</p>}
      {!d ? !err && <p className="muted">Comprobando dependencias…</p> : <>
        <div className="grid2">
          <div className="card">
            <h2>Estado</h2>
            <p>Versión <code>{d.version}</code> · comprobado {fmtTime(checked)}</p>
            <p>Modo «Solo local»: <strong>{d.local_only ? "activo — no sale contenido del equipo" : "inactivo"}</strong></p>
            <p>Presupuesto: USD {d.budget.per_request_usd} por consulta · USD {d.budget.daily_usd} diario<br />
              Hoy: USD {d.budget.today.accounted.toFixed(4)} contabilizado, USD {d.budget.today.reserved_open.toFixed(4)} reservado, {d.budget.today.unknown_cost_calls} con coste desconocido</p>
          </div>
          <div className="card">
            <h2>Acceso remoto</h2>
            <p>Esta sesión llega {d.remote.via_proxy ? "a través del proxy (Tailscale Serve)" : "directamente por loopback (este PC)"}.</p>
            <p>Origen público: {d.remote.public_origin ? <code>{d.remote.public_origin}</code> : <span className="muted">no configurado (ALICE_PUBLIC_ORIGIN); sin acceso remoto publicado</span>}</p>
            <p className="muted small-text">Grafana local: <code>{d.grafana_local}</code></p>
          </div>
        </div>
        <div className="card"><h2>Dependencias</h2><HealthGrid health={d.health} /></div>
      </>}
    </section>
  );
}

// ------------------------------------------------------------------ Settings
type SettingsResp = {
  local_only: boolean; cloud_enabled: boolean; budget_per_request_usd: number; budget_daily_usd: number; timezone: string;
  max_upload_mb: number; credentials: Record<string, string>; features: Record<string, boolean>;
};

export function SettingsPage() {
  const [d, err, load] = useLoad<SettingsResp>("/api/settings");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  async function toggle(v: boolean) {
    setSaving(true); setMsg("");
    try { await api("/api/settings", "PUT", { local_only: v }); setMsg(v ? "«Solo local» activado." : "«Solo local» desactivado."); }
    catch (e) { setMsg(errMsg(e)); }
    setSaving(false); load();
  }

  return (
    <section className="page">
      <PageHead title="Ajustes" sub="Política de salida, límites y credenciales." />
      {err && <p className="error" role="alert">{err}</p>}
      {!d ? !err && <p className="muted">Cargando…</p> : <>
        <div className="card">
          <h2>Política de salida</h2>
          <label className="switch">
            <input type="checkbox" checked={d.local_only} disabled={saving} onChange={(e) => toggle(e.target.checked)} />
            <span><strong>Solo local</strong> — el backend bloquea todo envío de contenido a proveedores externos (cloud y búsqueda web), no solo la interfaz.</span>
          </label>
          {msg && <p className="muted" role="status">{msg}</p>}
          <p>Cloud en configuración: <strong>{d.cloud_enabled ? "habilitado" : "deshabilitado"}</strong>
            {!d.cloud_enabled && <span className="muted"> (ALICE_CLOUD_ENABLED en .env; requiere reiniciar la API)</span>}</p>
          <p>Aun con cloud habilitado, el contenido PRIVATE o INTERNAL solo sale con tu «Autorizar una vez» en el chat.</p>
        </div>
        <div className="grid2">
          <div className="card">
            <h2>Límites</h2>
            <dl className="kv">
              <dt>Presupuesto por consulta</dt><dd>USD {d.budget_per_request_usd}</dd>
              <dt>Presupuesto diario</dt><dd>USD {d.budget_daily_usd}</dd>
              <dt>Tamaño máximo de subida</dt><dd>{d.max_upload_mb} MB</dd>
              <dt>Zona horaria</dt><dd>{d.timezone}</dd>
            </dl>
            <p className="muted small-text">Se cambian en .env y requieren reiniciar la API.</p>
          </div>
          <div className="card">
            <h2>Credenciales</h2>
            <p className="muted small-text">Nunca se muestran valores, solo si existen.</p>
            <dl className="kv">{Object.entries(d.credentials).map(([k, v]) => (
              <Fragment key={k}><dt><code>{k}</code></dt><dd className={v === "configurada" ? "ok-text" : "muted"}>{v}</dd></Fragment>))}</dl>
          </div>
        </div>
        <div className="card">
          <h2>Integraciones opcionales</h2>
          <dl className="kv">{Object.entries(d.features).map(([k, v]) => (
            <Fragment key={k}><dt>{k}</dt><dd className={v ? "ok-text" : "muted"}>{v ? "habilitada" : "deshabilitada"}</dd></Fragment>))}</dl>
          <p className="muted small-text">Su estado real (credencial, conexión) se ve en Sistema.</p>
        </div>
      </>}
    </section>
  );
}
