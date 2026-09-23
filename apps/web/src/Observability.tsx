import { useEffect, useState } from "react";
import { api, errMsg, fmtAge, fmtTime, fmtValue } from "./api";
import { HealthGrid, PageHead, type Health } from "./pages";

type Metric = { value: number | null; unit?: string; age_s?: number | null; error?: string };
type Overview = {
  health: Record<string, Health>; metrics: Record<string, Metric>;
  usage_today: { by_provider: Record<string, number>; spent: { accounted: number; reserved_open: number; unknown_cost_calls: number } };
  recent_requests: { request_id: string; started_at: string; route: string | null; provider: string | null; model: string | null; status: string; duration_s: number | null }[];
  grafana_url: string;
};
type Range = {
  metric: string; unit: string; description: string;
  coverage: { fraction: number; first: number | null; last: number | null; gaps: { from: number; to: number }[] };
  series: { labels: Record<string, string>; points: [number, number][] }[];
};

const TILES: [string, string][] = [
  ["host_cpu_percent", "CPU host"], ["host_mem_used_bytes", "RAM usada"], ["host_mem_total_bytes", "RAM total"],
  ["gpu_util_percent", "GPU"], ["gpu_mem_used_bytes", "VRAM usada"], ["gpu_mem_total_bytes", "VRAM total"], ["gpu_temp_c", "Temp. GPU"],
];
// Mirrors services/observability/prometheus.py CATALOG (no endpoint lists it yet).
const CATALOG = ["host_cpu_percent", "host_mem_used_bytes", "host_mem_available_bytes", "host_disk_free_bytes", "host_net_bytes_per_s",
  "host_uptime_s", "gpu_util_percent", "gpu_mem_used_bytes", "gpu_temp_c", "gpu_power_w", "ollama_loaded_vram_bytes",
  "alice_request_rate", "alice_p95_latency_s", "alice_errors_rate", "dependency_up", "scrape_up"];
const DEFAULT_CHARTS = ["host_cpu_percent", "host_mem_used_bytes", "gpu_util_percent", "gpu_mem_used_bytes", "gpu_temp_c", "alice_p95_latency_s"];
const WINDOWS: [number, string][] = [[15, "15 min"], [30, "30 min"], [60, "1 h"], [360, "6 h"], [1440, "24 h"]];
// Fixed-order series slots from theme.css (validated for CVD); never cycled past 6.
const COLORS = [1, 2, 3, 4, 5, 6].map((i) => `var(--series-${i})`);

export function Observability() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [err, setErr] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [extra, setExtra] = useState("alice_request_rate");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    api<Overview>("/api/observability/overview").then((o) => { setOv(o); setErr(""); }).catch((e) => setErr(errMsg(e)));
  }, [tick]);
  useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 15000); return () => clearInterval(t); }, []);

  const loopback = ["127.0.0.1", "localhost"].includes(location.hostname);
  return (
    <section className="page">
      <PageHead title="Observabilidad" sub="Métricas de Prometheus del equipo y registro local de consultas.">
        <label className="inline">Intervalo
          <select value={minutes} onChange={(e) => setMinutes(+e.target.value)}>
            {WINDOWS.map(([m, l]) => <option key={m} value={m}>{l}</option>)}
          </select>
        </label>
        <button className="ghost small" onClick={() => setTick((x) => x + 1)}>Actualizar</button>
        {ov && <a className="button" href={ov.grafana_url} target="_blank" rel="noopener noreferrer">Abrir Grafana</a>}
      </PageHead>
      {ov && !loopback && <p className="muted small-text">El enlace de Grafana apunta a {new URL(ov.grafana_url).host}; puede no ser accesible desde este dispositivo remoto.</p>}
      {err && <p className="error" role="alert">{err}</p>}

      {ov && <div className="tiles">
        {TILES.map(([k, label]) => {
          const mt = ov.metrics[k];
          return (
            <div key={k} className="tile" title={mt?.error ?? "Prometheus, consulta instantánea"}>
              <span className="tile-label">{label}</span>
              <strong className={mt?.value == null ? "tile-value empty" : "tile-value"}>{mt?.value == null ? "sin datos" : fmtValue(mt.value, mt.unit ?? "")}</strong>
              <small className="muted">{mt?.error ? "Prometheus no disponible" : mt?.value == null ? "sin muestra" : `muestra ${fmtAge(mt.age_s)}`}</small>
            </div>);
        })}
      </div>}

      <div className="charts">
        {DEFAULT_CHARTS.map((k) => <Chart key={k} metric={k} minutes={minutes} tick={tick} />)}
        <div className="chart-extra">
          <label className="inline">Otra métrica del catálogo
            <select value={extra} onChange={(e) => setExtra(e.target.value)}>
              {CATALOG.map((k) => <option key={k}>{k}</option>)}
            </select>
          </label>
          <Chart metric={extra} minutes={minutes} tick={tick} />
        </div>
      </div>

      {ov && <div className="grid2">
        <div className="card">
          <h2>Uso de hoy</h2>
          <p className="muted small-text">Fuente: registro local de Alice (SQLite).</p>
          {Object.keys(ov.usage_today.by_provider).length === 0 ? <p className="muted">Sin consultas completadas hoy.</p> :
            <Bars data={ov.usage_today.by_provider} />}
          <dl className="kv">
            <dt>Coste cloud contabilizado</dt><dd className="num">USD {ov.usage_today.spent.accounted.toFixed(4)}</dd>
            <dt>Reservado sin conciliar</dt><dd className="num">USD {ov.usage_today.spent.reserved_open.toFixed(4)}</dd>
            <dt>Llamadas con coste desconocido</dt><dd className="num">{ov.usage_today.spent.unknown_cost_calls}</dd>
          </dl>
        </div>
        <div className="card">
          <h2>Dependencias</h2>
          <HealthGrid health={ov.health} compact />
        </div>
      </div>}

      {ov && <div className="card">
        <h2>Últimas consultas</h2>
        {ov.recent_requests.length === 0 ? <p className="muted">Aún no hay consultas registradas.</p> :
          <div className="table-wrap"><table>
            <thead><tr><th>Id</th><th>Inicio</th><th>Ruta</th><th>Proveedor</th><th>Modelo</th><th>Estado</th><th>Duración</th></tr></thead>
            <tbody>{ov.recent_requests.map((r) => (
              <tr key={r.request_id + r.started_at}><td><code>{r.request_id}</code></td><td className="nowrap">{fmtTime(r.started_at)}</td>
                <td>{r.route ?? "—"}</td><td>{r.provider ?? "—"}</td><td>{r.model ?? "—"}</td><td>{r.status}</td>
                <td>{r.duration_s == null ? "—" : `${r.duration_s.toFixed(2)} s`}</td></tr>))}
            </tbody></table></div>}
      </div>}
    </section>
  );
}

// Horizontal bars: consultas por proveedor (magnitude, one hue; value labelled in text ink).
function Bars({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...rows.map(([, n]) => n), 1);
  return (
    <ul className="bars" aria-label="Consultas completadas hoy por proveedor">
      {rows.map(([p, n]) => (
        <li key={p}><span>{p}</span><span className="bar"><i style={{ width: `${(n / max) * 100}%` }} /></span><span className="num">{n}</span></li>))}
    </ul>
  );
}

function Chart({ metric, minutes, tick }: { metric: string; minutes: number; tick: number }) {
  const [r, setR] = useState<Range | null>(null);
  const [err, setErr] = useState("");
  const [hover, setHover] = useState<number | null>(null); // fraction 0..1 across the plot
  useEffect(() => {
    let live = true;
    api<Range>(`/api/observability/range?metric=${encodeURIComponent(metric)}&minutes=${minutes}`)
      .then((x) => { if (live) { setR(x); setErr(""); } })
      .catch((e) => { if (live) { setR(null); setErr(errMsg(e)); } });
    return () => { live = false; };
  }, [metric, minutes, tick]);

  const W = 320, H = 140;
  const end = Date.now() / 1000, start = end - minutes * 60;
  const pts = r?.series.flatMap((s) => s.points) ?? [];
  const hasData = pts.length > 0;
  let lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  if (r?.unit.startsWith("%")) { lo = 0; hi = Math.max(100, hi); }
  if (hasData && lo === hi) { lo -= 1; hi += 1; }
  const x = (t: number) => ((t - start) / (end - start)) * W;
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  const last = r?.coverage.last;

  function path(points: [number, number][]) {
    // Break the line on gaps (> 3x typical step): missing data is never drawn as a value.
    const steps = points.slice(1).map((p, i) => p[0] - points[i][0]).sort((a, b) => a - b);
    const step = steps[Math.floor(steps.length / 2)] ?? 15;
    return points.map((p, i) => `${i === 0 || p[0] - points[i - 1][0] > 3 * step ? "M" : "L"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  }
  const label = (l: Record<string, string>) => Object.entries(l).filter(([k]) => !["__name__", "job", "instance"].includes(k)).map(([, v]) => v).join(" ") || "serie";
  // Nearest sample per series to the hovered time (only within 2 min, so gaps read as gaps).
  const hoverT = hover == null ? null : start + hover * (end - start);
  const nearest = hoverT == null || !r ? [] : r.series.slice(0, 6).map((s, i) => {
    const p = s.points.reduce<[number, number] | null>((b, q) => (!b || Math.abs(q[0] - hoverT) < Math.abs(b[0] - hoverT) ? q : b), null);
    return { i, name: label(s.labels), p: p && Math.abs(p[0] - hoverT) < 120 ? p : null };
  });

  return (
    <figure className="chart card">
      <figcaption><strong>{r?.description ?? metric}</strong> <span className="muted">[{r?.unit ?? "—"}]</span></figcaption>
      {hasData ? (
        <div className="plot" onPointerMove={(e) => { const b = e.currentTarget.getBoundingClientRect(); setHover(Math.min(1, Math.max(0, (e.clientX - b.left) / b.width))); }}
          onPointerLeave={() => setHover(null)}>
          <span className="y-hi">{fmtValue(hi, r!.unit)}</span><span className="y-lo">{fmtValue(lo, r!.unit)}</span>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${metric}, últimos ${minutes} minutos`}>
            {[0, 0.5, 1].map((f) => <line key={f} x1={0} x2={W} y1={f * H} y2={f * H} className="grid" />)}
            {r!.series.slice(0, 6).map((s, i) => <path key={i} d={path(s.points)} style={{ stroke: COLORS[i] }} className="line" />)}
            {hover != null && <line x1={hover * W} x2={hover * W} y1={0} y2={H} className="cross" />}
          </svg>
          {hover != null && hoverT != null && (
            <div className={`tip ${hover > 0.6 ? "left" : ""}`} style={{ left: `${hover * 100}%` }}>
              <div className="muted">{new Date(hoverT * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}</div>
              {nearest.map((n) => (
                <div key={n.i}>{r!.series.length > 1 && <i style={{ background: COLORS[n.i] }} />}{r!.series.length > 1 ? `${n.name}: ` : ""}
                  <strong>{n.p ? fmtValue(n.p[1], r!.unit) : "sin muestra"}</strong></div>))}
            </div>)}
          <div className="x-axis"><span>−{minutes} min</span><span>ahora</span></div>
        </div>
      ) : <div className="nodata">sin datos{err ? ` — ${err}` : ""}</div>}
      <div className="muted small-text chart-meta">
        {hasData && <span>rango {fmtValue(Math.min(...pts.map((p) => p[1])), r!.unit)} – {fmtValue(Math.max(...pts.map((p) => p[1])), r!.unit)}</span>}
        <span>Prometheus · {minutes} min · última muestra {last ? fmtAge(end - last) : "sin datos"}</span>
        {r && hasData && <span>cobertura {(r.coverage.fraction * 100).toFixed(0)}%{r.coverage.gaps.length ? `, ${r.coverage.gaps.length} huecos` : ""}</span>}
      </div>
      {r && r.series.length > 1 && <div className="legend">{r.series.slice(0, 6).map((s, i) => (
        <span key={i}><i style={{ background: COLORS[i] }} />{label(s.labels)}: {fmtValue(s.points.at(-1)?.[1], r.unit)}</span>))}
        {r.series.length > 6 && <span className="muted">+{r.series.length - 6} series más (ver en Grafana)</span>}</div>}
    </figure>
  );
}
