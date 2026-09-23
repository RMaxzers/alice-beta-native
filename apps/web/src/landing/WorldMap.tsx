import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { geoGraticule10, geoNaturalEarth1, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { GeometryCollection } from "topojson-specification";
import { animate, createDrawable, createTimeline, stagger } from "animejs";
import world from "world-atlas/countries-110m.json";
import "./landing.css";

// Colors come from data-tone -> CSS custom properties in landing.css (theme tokens only).
export type Tone = "local" | "knowledge" | "obs" | "cloud" | "web" | "muted";
export interface MapNode {
  id: string; label: string; sub?: string; tone: Tone;
  lonLat?: [number, number];   // real (approximate) geographic position
  at?: [number, number];       // OR a fixed spot in the frame (0..1), for things with no known location
  anchor?: "start" | "end";    // label side
}
export interface MapLink { from: string; to: string; tone: Tone; label?: string; locked?: boolean }
/** One real request: an arc from -> to (or a ping when from === to). Keys must be unique. */
export interface MapEvent { key: string; from: string; to: string; tone: Tone }

const W = 960, H = 500;
const projection = geoNaturalEarth1().rotate([40, 0]).fitExtent([[6, 6], [W - 6, H - 6]], { type: "Sphere" });
const path = geoPath(projection);
const countries = feature(world, world.objects.countries as GeometryCollection).features;
const CHILE = countries.findIndex((f) => f.id === "152");
const SPHERE = path({ type: "Sphere" }) ?? "";
const GRAT = path(geoGraticule10()) ?? "";
const LAND = countries.map((f) => path(f) ?? "");

export const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function arcPath([x1, y1]: number[], [x2, y2]: number[]) {
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1;
  const k = 0.22 * (dx >= 0 ? 1 : -1); // bulge to the upper side of the chord
  const cx = mx + dy * k, cy = my - dx * k;
  return { d: `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`, mid: [(x1 + 2 * cx + x2) / 4, (y1 + 2 * cy + y2) / 4] };
}

export function WorldMap({ nodes, links = [], events = [], label, intro = false, className = "" }: {
  nodes: MapNode[]; links?: MapLink[]; events?: MapEvent[]; label: string; intro?: boolean; className?: string;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const done = useRef(new Set<string>());
  const pos = useMemo(() => {
    const m: Record<string, number[]> = {};
    for (const n of nodes) m[n.id] = n.lonLat ? projection(n.lonLat)! : [n.at![0] * W, n.at![1] * H];
    return m;
  }, [nodes]);
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);

  // Intro: sphere outline draws itself, countries appear outward from Chile, then links and nodes.
  useLayoutEffect(() => {
    if (!intro || reducedMotion() || !svg.current) return;
    const $ = (s: string) => svg.current!.querySelectorAll(s);
    const tl = createTimeline({ defaults: { ease: "outQuad" } })
      .add(createDrawable($(".wm-sphere")), { draw: ["0 0", "0 1"], duration: 1100 }, 0)
      .add($(".wm-grat"), { opacity: [0, 1], duration: 900 }, 200)
      .add($(".wm-land"), { opacity: [0, 1], duration: 500, delay: stagger(5, { from: Math.max(CHILE, 0) }) }, 250)
      .add($(".wm-link"), { opacity: [0, 1], duration: 600, delay: stagger(180) }, 1100)
      .add($(".wm-node"), { opacity: [0, 1], scale: [0.4, 1], duration: 500, delay: stagger(120), ease: "outBack" }, 1000)
      .add($(".wm-label"), { opacity: [0, 1], duration: 500, delay: stagger(90) }, 1300);
    return () => { tl.revert(); };
  }, [intro]);

  // One arc/ping per event, played once per key. Reduced motion: CSS shows them statically instead.
  useEffect(() => {
    if (reducedMotion() || !svg.current) return;
    const anims: { cancel(): unknown }[] = [];
    let i = 0;
    for (const e of events) {
      if (done.current.has(e.key)) continue;
      done.current.add(e.key);
      const delay = i++ * 450;
      const q = (k: string) => svg.current!.querySelector<SVGGeometryElement>(`[data-ev="${k}"]`);
      const arc = q(e.key + ":arc"), ping = q(e.key + ":ping");
      if (arc) {
        const [d] = createDrawable(arc, 0, 0);
        arc.style.opacity = "1";
        anims.push(animate(d, { draw: ["0 0", "0 1", "1 1"], duration: 2000, delay, ease: "inOutSine" }));
      }
      if (ping) anims.push(animate(ping, { r: [4, 30], opacity: [0.9, 0], duration: 1300, delay: delay + (arc ? 900 : 0), ease: "outQuad" }));
    }
    return () => anims.forEach((a) => a.cancel());
  }, [events]);

  const linkText = (l: MapLink) => `${byId[l.from]?.label} → ${byId[l.to]?.label}${l.label ? ` (${l.label})` : ""}`;

  return (
    <figure className={`wm ${className}`}>
      <svg ref={svg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        <path className="wm-sphere" d={SPHERE} />
        <path className="wm-grat" d={GRAT} />
        <g>{LAND.map((d, i) => <path key={i} className="wm-land" d={d} />)}</g>
        <g>
          {links.map((l) => {
            const a = arcPath(pos[l.from], pos[l.to]);
            return (
              <g key={l.from + l.to} className="wm-link" data-tone={l.tone}>
                <path d={a.d} />
                {l.label && (
                  <g transform={`translate(${a.mid[0]},${a.mid[1]})`}>
                    {l.locked && <g className="wm-lock" transform="translate(-13,-34) scale(1.45)">
                      <rect x="3.5" y="8" width="11" height="9" rx="1.5" /><path d="M6 8V5.5a3 3 0 0 1 6 0V8" />
                    </g>}
                    <text className="wm-linklabel" y={l.locked ? 12 : 4} textAnchor="middle">{l.label}</text>
                  </g>
                )}
              </g>
            );
          })}
        </g>
        <g>
          {events.map((e) => {
            const [x, y] = pos[e.to] ?? pos[e.from] ?? [0, 0];
            return (
              <g key={e.key} className="wm-ev" data-tone={e.tone}>
                {e.from !== e.to && pos[e.from] && pos[e.to] && <path data-ev={e.key + ":arc"} d={arcPath(pos[e.from], pos[e.to]).d} />}
                <circle data-ev={e.key + ":ping"} cx={x} cy={y} r="4" />
              </g>
            );
          })}
        </g>
        <g>
          {nodes.map((n) => {
            const [x, y] = pos[n.id], end = n.anchor === "end", dx = end ? -16 : 16;
            return (
              <g key={n.id} data-tone={n.tone}>
                <g transform={`translate(${x},${y})`}>
                  <g className="wm-node">
                    <circle className="wm-halo" r="14" />
                    <circle className="wm-dot" r={n.at ? 6 : 7} />
                  </g>
                </g>
                <text className="wm-label" x={x + dx} y={y} textAnchor={end ? "end" : "start"}>
                  <tspan dy="-0.1em">{n.label}</tspan>
                  {n.sub && <tspan className="wm-sub" x={x + dx} dy="1.25em">{n.sub}</tspan>}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <ul className="sr-only">
        {nodes.map((n) => <li key={n.id}>{n.label}{n.sub ? ` ${n.sub}` : ""}</li>)}
        {links.map((l) => <li key={l.from + l.to}>{linkText(l)}</li>)}
      </ul>
    </figure>
  );
}

// Alice's real topology. Places are approximate on purpose and say so.
export const ARCH_NODES: MapNode[] = [
  { id: "pc", label: "Este PC · Santiago", sub: "(aprox., por zona horaria)", tone: "local", lonLat: [-70.67, -33.45] },
  { id: "openrouter", label: "OpenRouter · EE. UU.", sub: "(intermediario, ubicación aprox.)", tone: "cloud", lonLat: [-98, 39] },
  { id: "web", label: "Búsqueda web (Tavily)", sub: "ubicación no fija", tone: "web", at: [0.965, 0.07], anchor: "end" },
  { id: "laptop", label: "Laptop remoto (tailnet)", sub: "ubicación desconocida", tone: "muted", at: [0.035, 0.93] },
];
export const ARCH_LINKS: MapLink[] = [
  { from: "pc", to: "openrouter", tone: "cloud", label: "solo con tu autorización", locked: true },
  { from: "pc", to: "web", tone: "web", label: "búsqueda web" },
  { from: "laptop", to: "pc", tone: "muted", label: "red privada" },
];
