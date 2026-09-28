import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { animate, createDrawable, createTimeline, stagger } from "animejs";
import "./landing.css";

// Colors come from data-tone -> CSS custom properties in landing.css (theme tokens only).
export type Tone = "local" | "knowledge" | "obs" | "cloud" | "web" | "muted" | "data" | "idea" | "answer";
export interface NetNode {
  id: string; label: string; sub?: string; tone: Tone;
  at: [number, number];        // fixed spot in the frame (0..1 fractional, left-to-right / top-to-bottom)
  r?: number;                  // dot radius, defaults to 7 — lets a real count drive size
  anchor?: "start" | "end" | "middle";
}
export interface NetLink { from: string; to: string; tone: Tone }
/** One real event: an arc from -> to (or a ping when from === to). Keys must be unique. */
export interface NetEvent { key: string; from: string; to: string; tone: Tone }

const W = 720, H = 420;

export const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function arcPath([x1, y1]: number[], [x2, y2]: number[]) {
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1;
  const k = 0.22 * (dx >= 0 ? 1 : -1); // bulge to the upper side of the chord
  const cx = mx + dy * k, cy = my - dx * k;
  return `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`;
}

// Deterministic pseudo-random star field for the nebula backdrop — decorative only, never mistaken for data.
function starField(seed: number, n: number) {
  let s = seed;
  const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  return Array.from({ length: n }, () => ({ x: rnd() * W, y: rnd() * H, r: 0.4 + rnd() * 1.1, o: 0.12 + rnd() * 0.35 }));
}
const STARS = starField(7, 80);

export function NetworkArt({ nodes, links = [], events = [], label, intro = false, nebula = false, className = "" }: {
  nodes: NetNode[]; links?: NetLink[]; events?: NetEvent[]; label: string; intro?: boolean; nebula?: boolean; className?: string;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const done = useRef(new Set<string>());
  const pos = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, [n.at[0] * W, n.at[1] * H]])), [nodes]);
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);

  // Intro: nebula fades in, then links draw, then nodes settle, then labels.
  useLayoutEffect(() => {
    if (!intro || reducedMotion() || !svg.current) return;
    const $ = (s: string) => svg.current!.querySelectorAll(s);
    const tl = createTimeline({ defaults: { ease: "outQuad" } })
      .add($(".na-star"), { opacity: [0, 1], duration: 1200, delay: stagger(6) }, 0)
      .add($(".na-link"), { opacity: [0, 1], duration: 650, delay: stagger(80) }, 300)
      .add($(".na-node"), { opacity: [0, 1], scale: [0.4, 1], duration: 480, delay: stagger(70), ease: "outBack" }, 550)
      .add($(".na-label"), { opacity: [0, 1], duration: 420, delay: stagger(60) }, 850);
    return () => { tl.revert(); };
  }, [intro]);

  // One arc/ping per real event, played once per key. Reduced motion: CSS shows them statically instead.
  useEffect(() => {
    if (reducedMotion() || !svg.current) return;
    const anims: { cancel(): unknown }[] = [];
    let i = 0;
    for (const e of events) {
      if (done.current.has(e.key)) continue;
      done.current.add(e.key);
      const delay = i++ * 320;
      const q = (k: string) => svg.current!.querySelector<SVGGeometryElement>(`[data-ev="${k}"]`);
      const arc = q(e.key + ":arc"), ping = q(e.key + ":ping");
      if (arc) {
        const [d] = createDrawable(arc, 0, 0);
        arc.style.opacity = "1";
        anims.push(animate(d, { draw: ["0 0", "0 1", "1 1"], duration: 1400, delay, ease: "inOutSine" }));
      }
      if (ping) anims.push(animate(ping, { r: [3, 20], opacity: [0.9, 0], duration: 1000, delay: delay + (arc ? 700 : 0), ease: "outQuad" }));
    }
    return () => anims.forEach((a) => a.cancel());
  }, [events]);

  const linkText = (l: NetLink) => `${byId[l.from]?.label} → ${byId[l.to]?.label}`;

  return (
    <figure className={`na ${className}`}>
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        <rect className="na-bg" x="0" y="0" width={W} height={H} />
        {nebula && (
          <>
            <defs>
              <radialGradient id="na-neb-a" cx="18%" cy="18%" r="60%"><stop offset="0%" stopColor="var(--accent)" stopOpacity=".18" /><stop offset="100%" stopColor="var(--accent)" stopOpacity="0" /></radialGradient>
              <radialGradient id="na-neb-b" cx="85%" cy="85%" r="65%"><stop offset="0%" stopColor="var(--accent-2)" stopOpacity=".14" /><stop offset="100%" stopColor="var(--accent-2)" stopOpacity="0" /></radialGradient>
            </defs>
            <rect x="0" y="0" width={W} height={H} fill="url(#na-neb-a)" />
            <rect x="0" y="0" width={W} height={H} fill="url(#na-neb-b)" />
            <g>{STARS.map((s, i) => <circle key={i} className="na-star" cx={s.x} cy={s.y} r={s.r} opacity={s.o} />)}</g>
          </>
        )}
        <g>
          {links.map((l) => <path key={l.from + l.to} className="na-link" data-tone={l.tone} d={arcPath(pos[l.from], pos[l.to])} />)}
        </g>
        <g>
          {events.map((e) => {
            const [x, y] = pos[e.to] ?? pos[e.from] ?? [0, 0];
            return (
              <g key={e.key} className="na-ev" data-tone={e.tone}>
                {e.from !== e.to && pos[e.from] && pos[e.to] && <path data-ev={e.key + ":arc"} d={arcPath(pos[e.from], pos[e.to])} />}
                <circle data-ev={e.key + ":ping"} cx={x} cy={y} r="3" />
              </g>
            );
          })}
        </g>
        <g>
          {nodes.map((n) => {
            const [x, y] = pos[n.id];
            const r = n.r ?? 7;
            const anchor = n.anchor ?? "middle";
            const dx = anchor === "end" ? -(r + 10) : anchor === "start" ? r + 10 : 0;
            const dy = -(r + 9);
            return (
              <g key={n.id} data-tone={n.tone}>
                {/* Position on the outer group: anime.js scales .na-node via CSS transform, which would drop an SVG translate. */}
                <g transform={`translate(${x},${y})`}>
                  <g className="na-node">
                    <circle className="na-halo" r={r + 7} />
                    <circle className="na-dot" r={r} />
                  </g>
                </g>
                <text className="na-label" x={x + dx} y={y + dy} textAnchor={anchor}>{n.label}</text>
                {n.sub && <text className="na-sub" x={x + dx} y={y + dy + 15} textAnchor={anchor}>{n.sub}</text>}
              </g>
            );
          })}
        </g>
      </svg>
      <ul className="sr-only">
        {nodes.map((n) => <li key={n.id}>{n.label}{n.sub ? ` — ${n.sub}` : ""}</li>)}
        {links.map((l) => <li key={l.from + l.to}>{linkText(l)}</li>)}
      </ul>
    </figure>
  );
}

// Conceptual illustration for the login screen only — not a data visualization. Three groups:
// what Alice reads (documents/data), how it thinks (retrieval/reasoning/verification), what comes out (the answer).
export const HERO_NODES: NetNode[] = [
  { id: "doc1", label: "Documentos", tone: "data", at: [0.10, 0.20], r: 7, anchor: "start" },
  { id: "doc2", label: "Registros", tone: "data", at: [0.06, 0.52], r: 6, anchor: "start" },
  { id: "doc3", label: "Tablas", tone: "data", at: [0.12, 0.84], r: 6, anchor: "start" },
  { id: "idea1", label: "Recuperación", tone: "idea", at: [0.48, 0.14], r: 6 },
  { id: "idea2", label: "Razonamiento", tone: "idea", at: [0.50, 0.5], r: 7 },
  { id: "idea3", label: "Verificación", tone: "idea", at: [0.46, 0.86], r: 6 },
  { id: "answer", label: "Respuesta", tone: "answer", at: [0.88, 0.5], r: 9 },
];
export const HERO_LINKS: NetLink[] = [
  { from: "doc1", to: "idea1", tone: "data" }, { from: "doc1", to: "idea2", tone: "data" },
  { from: "doc2", to: "idea2", tone: "data" },
  { from: "doc3", to: "idea2", tone: "data" }, { from: "doc3", to: "idea3", tone: "data" },
  { from: "idea1", to: "answer", tone: "idea" }, { from: "idea2", to: "answer", tone: "idea" }, { from: "idea3", to: "answer", tone: "idea" },
];
