import { useEffect, useState } from "react";
import { api, errMsg } from "../api";
import { ARCH_LINKS, ARCH_NODES, WorldMap, type MapEvent, type Tone } from "./WorldMap";
import "./landing.css";

interface Req { request_id: string; started_at: string; route: string | null; provider: string | null; model: string | null; status: string; duration_s: number | null }
interface Overview { recent_requests: Req[]; usage_today?: { by_provider: Record<string, number> } }

// Where a request actually went is decided by the provider that served it, not by the route it asked for:
// a cloud route without consent never reached OpenRouter, so it stays a local ping.
function place(r: Req): { to: string; tone: Tone; dest: string } {
  if (r.provider === "openrouter") return { to: "openrouter", tone: "cloud", dest: "Nube · OpenRouter" };
  if (r.provider === "tavily") return { to: "web", tone: "web", dest: "Web · Tavily" };
  const tone: Tone = r.route === "LOCAL_RAG" ? "knowledge" : r.route === "OBSERVABILITY" ? "obs" : r.route ? "local" : "muted";
  return { to: "pc", tone, dest: "Este PC" };
}

// Same buckets the backend uses for "Hoy" (services/observability/answers.py usage_today).
const LOCAL_PROVIDERS = ["ollama", "local-tools", "ninguno"];

// Survives tab switches: requests seen before this view (re)mounts are not replayed as new.
let seen: Set<string> | null = null;

const LEGEND: [Tone, string][] = [
  ["local", "Local"], ["knowledge", "Conocimiento (RAG)"], ["obs", "Observabilidad"], ["cloud", "Nube · OpenRouter"], ["web", "Web · Tavily"],
];
const MAP_LABEL = "Mapa en vivo de las consultas: las locales se marcan en este PC (Santiago, aproximado); " +
  "las que salen a la nube van a OpenRouter (EE. UU., aproximado) y las de búsqueda web a Tavily. El detalle está en la tabla.";
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });

export function LiveMap() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [events, setEvents] = useState<MapEvent[]>([]);
  const [err, setErr] = useState("");
  const [updated, setUpdated] = useState<{ at: string; fresh: number } | null>(null);

  useEffect(() => {
    let alive = true, busy = false;
    // The first load always runs (a tab opened in the background must not stay on "Cargando…");
    // after that, polling pauses while the page is hidden.
    async function poll(first = false) {
      if (busy || (!first && document.hidden)) return;
      busy = true;
      try {
        const o = await api<Overview>("/api/observability/overview");
        if (!alive) return;
        const fresh = seen ? o.recent_requests.filter((r) => !seen!.has(r.request_id)) : [];
        seen = new Set([...(seen ?? []), ...o.recent_requests.map((r) => r.request_id)]);
        // oldest first so the replay follows arrival order
        setEvents(fresh.reverse().map((r) => ({ key: r.request_id, from: "pc", ...place(r) })));
        setOv(o); setErr("");
        setUpdated({ at: new Date().toISOString(), fresh: fresh.length });
      } catch (e) { if (alive) setErr(errMsg(e)); } finally { busy = false; }
    }
    poll(true);
    const t = setInterval(poll, 10_000);
    const onVis = () => { if (!document.hidden) poll(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { alive = false; clearInterval(t); document.removeEventListener("visibilitychange", onVis); };
  }, []);

  const by = ov?.usage_today?.by_provider;
  const count = (ps: string[]) => ps.reduce((n, p) => n + (by?.[p] ?? 0), 0);
  const recent = ov?.recent_requests.slice(0, 6) ?? [];

  return (
    <section className="lm" aria-labelledby="lm-title">
      <div className="lm-head">
        <h2 id="lm-title">Adónde van tus consultas</h2>
        <p className="lm-status" aria-live="polite">
          {updated ? `Actualizado ${hhmm(updated.at)}${updated.fresh ? ` · ${updated.fresh} nueva${updated.fresh > 1 ? "s" : ""}` : ""}` : "Cargando…"}
        </p>
      </div>
      {err && <p className="error" role="alert">No se pudo actualizar el mapa: {err}. Se reintenta en 10 s.</p>}

      <ul className="lm-legend" aria-label="Leyenda">
        {LEGEND.map(([tone, text]) => (
          <li key={tone} data-tone={tone}><svg width="22" height="8" aria-hidden="true"><line x1="1" y1="4" x2="21" y2="4" /></svg>{text}</li>
        ))}
      </ul>

      <div className="lm-map">
        <WorldMap nodes={ARCH_NODES} links={ARCH_LINKS} events={events} label={MAP_LABEL} />
      </div>

      {by && (
        <dl className="lm-stats" aria-label="Consultas completadas hoy">
          <div data-tone="local"><dt>Hoy · locales</dt><dd>{count(LOCAL_PROVIDERS)}</dd></div>
          <div data-tone="cloud"><dt>Hoy · nube (OpenRouter)</dt><dd>{count(["openrouter"])}</dd></div>
          <div data-tone="web"><dt>Hoy · web (Tavily)</dt><dd>{count(["tavily"])}</dd></div>
        </dl>
      )}

      {ov && (recent.length === 0 ? <p className="lm-empty">Aún no hay consultas recientes; haz una pregunta en Chat.</p> : (
        <table className="lm-feed">
          <caption className="sr-only">Últimas consultas registradas</caption>
          <thead><tr><th>Hora</th><th>Ruta</th><th>Destino</th><th className="opt">Estado</th><th className="opt num">Duración</th></tr></thead>
          <tbody>
            {recent.map((r) => {
              const p = place(r);
              return (
                <tr key={r.request_id}>
                  <td>{hhmm(r.started_at)}</td>
                  <td>{r.route ?? "—"}</td>
                  <td><span className="lm-dest" data-tone={p.tone}>{p.dest}</span></td>
                  <td className="opt">{r.status}</td>
                  <td className="opt num">{r.duration_s == null ? "—" : `${r.duration_s.toFixed(1)} s`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ))}
    </section>
  );
}
