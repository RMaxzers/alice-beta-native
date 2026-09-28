// Mapa view: documents connected by semantic similarity, laid out with a tiny force simulation
// (knowledge/force.ts) and drawn on a plain <canvas> — no WebGL, no charting dependency. The canvas
// is decorative for assistive tech (aria-hidden): the <details> list right below it is the real,
// keyboard- and screen-reader-accessible copy of the same nodes and their neighbors.
import { useEffect, useMemo, useRef, useState } from "react";
import { api, errMsg } from "../api";
import type { Privacy } from "../Chat";
import { DocDetail, type Neighbor } from "./DocDetail";
import { bfsPath, layoutStatic, seedCircle, stepForce, type SimEdge, type SimNode } from "./force";
import { GROUP_COLOR_VAR, GROUP_LABEL, kindGroup, reducedMotion, type Doc, type DocActions, type KindGroup } from "./shared";

const FPS = 30;
const FRAME_MS = 1000 / FPS;
const SETTLE_EPS = 0.05; // average per-node displacement below this: stop stepping, keep drawing the final frame
const MAX_TICKS = 600;

interface MapNode { id: string; name: string; kind: string; privacy: Privacy; chunks: number }
interface MapResp { nodes: MapNode[]; edges: SimEdge[] }

function useLatest<T>(v: T) { const r = useRef(v); r.current = v; return r; }

interface Colors { text: string; lineStrong: string; accent: string; font: string; groups: Record<KindGroup, string> }
function readColors(el: Element): Colors {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    text: v("--text"), lineStrong: v("--line-strong"), accent: v("--accent"), font: v("--font-sans"),
    groups: { pdf: v(GROUP_COLOR_VAR.pdf), texto: v(GROUP_COLOR_VAR.texto), hojas: v(GROUP_COLOR_VAR.hojas), logs: v(GROUP_COLOR_VAR.logs), otros: v(GROUP_COLOR_VAR.otros) },
  };
}
// Tokens are always "#rrggbb" (theme.css) — no general CSS color parsing needed.
function alpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}
const nodeRadius = (chunks: number) => Math.min(28, 7 + Math.sqrt(Math.max(1, chunks)) * 2.5);

export function KnowledgeMap({ docs, selectedId, onSelect, confirm, onAskDelete, onConfirmDelete, onCancelDelete, onCancelProcessing, onGoUpload }: {
  docs: Doc[]; selectedId: string | null; onSelect: (id: string | null) => void; onGoUpload: () => void;
} & DocActions) {
  const [data, setData] = useState<MapResp | null>(null);
  const [err, setErr] = useState("");
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [path, setPath] = useState<string[] | null | undefined>(undefined);

  useEffect(() => {
    api<MapResp>("/api/knowledge/map").then((d) => { setData(d); setErr(""); }).catch((e) => setErr(errMsg(e)));
  }, []);
  useEffect(() => { setPath(undefined); }, [fromId, toId]);

  const byNodeId = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);
  const neighborsOf = (id: string): Neighbor[] =>
    (data?.edges ?? [])
      .filter((e) => e.source === id || e.target === id)
      .map((e) => { const nid = e.source === id ? e.target : e.source; return { id: nid, name: byNodeId.get(nid)?.name ?? nid, similarity: e.similarity }; })
      .sort((a, b) => b.similarity - a.similarity);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pathRef = useLatest(path);
  const selectedRef = useLatest(selectedId);
  const onSelectRef = useLatest(onSelect);
  const drawRef = useRef<() => void>(() => {});

  useEffect(() => {
    const box = wrapRef.current, el = canvasRef.current;
    const ctx = el?.getContext("2d");
    if (!data || data.nodes.length < 2 || !box || !el || !ctx) return;

    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = Math.max(560, Math.min(900, 560 + data.nodes.length * 14));
    const h = Math.round(w * 0.62);
    el.width = Math.round(w * dpr); el.height = Math.round(h * dpr);
    el.style.width = `${w}px`; el.style.height = `${h}px`;
    const colors = readColors(el);

    const nodes: SimNode[] = data.nodes.map((n) => ({ id: n.id, x: 0, y: 0, vx: 0, vy: 0, r: nodeRadius(n.chunks) }));
    seedCircle(nodes, w, h);
    const byId = new Map(nodes.map((n) => [n.id, n]));

    function pathEdgeSet(p: string[] | null): Set<string> {
      const s = new Set<string>();
      if (!p) return s;
      for (let i = 0; i < p.length - 1; i++) s.add(`${p[i]}|${p[i + 1]}`);
      return s;
    }

    function draw() {
      ctx!.clearRect(0, 0, el!.width, el!.height);
      const p = pathRef.current ?? null;
      const onPath = pathEdgeSet(p);
      const pathNodes = new Set(p ?? []);

      for (const e of data!.edges) {
        const a = byId.get(e.source), b = byId.get(e.target);
        if (!a || !b) continue;
        const highlighted = onPath.has(`${a.id}|${b.id}`) || onPath.has(`${b.id}|${a.id}`);
        ctx!.strokeStyle = highlighted ? alpha(colors.accent, 0.9) : alpha(colors.lineStrong, 0.15 + e.similarity * 0.4);
        ctx!.lineWidth = (highlighted ? 2.2 : 0.6 + e.similarity * 1.8) * dpr;
        ctx!.beginPath();
        ctx!.moveTo(a.x * dpr, a.y * dpr);
        ctx!.lineTo(b.x * dpr, b.y * dpr);
        ctx!.stroke();
      }

      for (const n of nodes) {
        const src = byNodeId.get(n.id);
        const color = colors.groups[kindGroup(src?.kind ?? "")];
        ctx!.fillStyle = color;
        ctx!.beginPath();
        ctx!.arc(n.x * dpr, n.y * dpr, n.r * dpr, 0, Math.PI * 2);
        ctx!.fill();
        if (n.id === selectedRef.current || pathNodes.has(n.id)) {
          ctx!.strokeStyle = n.id === selectedRef.current ? colors.text : colors.accent;
          ctx!.lineWidth = 2 * dpr;
          ctx!.beginPath();
          ctx!.arc(n.x * dpr, n.y * dpr, (n.r + 3) * dpr, 0, Math.PI * 2);
          ctx!.stroke();
        }
        if (data!.nodes.length <= 40) {
          ctx!.fillStyle = alpha(colors.text, 0.75);
          ctx!.font = `${11 * dpr}px ${colors.font}`;
          ctx!.textAlign = "center";
          const label = (src?.name ?? "").length > 16 ? `${src!.name.slice(0, 15)}…` : (src?.name ?? "");
          ctx!.fillText(label, n.x * dpr, (n.y + n.r + 13) * dpr);
        }
      }
    }
    drawRef.current = draw;

    if (reducedMotion()) { layoutStatic(nodes, data.edges, w, h, 300); draw(); return; }

    let raf = 0, last = 0, ticks = 0, settled = false;
    function loop(t: number) {
      if (t - last >= FRAME_MS) {
        last = t;
        if (!settled) {
          const disp = stepForce(nodes, data!.edges, w, h);
          ticks++;
          if (disp / nodes.length < SETTLE_EPS || ticks > MAX_TICKS) settled = true;
        }
        draw();
      }
      if (!settled) raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    function onVis() {
      cancelAnimationFrame(raf);
      if (!document.hidden && !settled) { last = 0; raf = requestAnimationFrame(loop); }
    }
    document.addEventListener("visibilitychange", onVis);

    function pick(clientX: number, clientY: number): SimNode | null {
      const rect = el!.getBoundingClientRect();
      const x = clientX - rect.left, y = clientY - rect.top;
      let hit: SimNode | null = null, best = Infinity;
      for (const n of nodes) {
        const d = Math.hypot(n.x - x, n.y - y);
        if (d <= n.r + 4 && d < best) { hit = n; best = d; }
      }
      return hit;
    }
    function onMove(e: MouseEvent) { el!.style.cursor = pick(e.clientX, e.clientY) ? "pointer" : "default"; }
    function onClick(e: MouseEvent) { const n = pick(e.clientX, e.clientY); if (n) onSelectRef.current(n.id); }
    el.addEventListener("mousemove", onMove);
    el.addEventListener("click", onClick);

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("click", onClick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- selectedId/path are read via refs so the simulation isn't restarted by selection alone
  }, [data]);

  // Redraw (without restarting the simulation) when selection or the traced path changes.
  useEffect(() => { drawRef.current(); }, [selectedId, path]);

  const selectedDoc = docs.find((d) => d.document_id === selectedId) ?? null;
  const selectedNode = selectedId ? byNodeId.get(selectedId) : null;

  const groupsPresent = useMemo(() => {
    const set = new Set<KindGroup>();
    for (const n of data?.nodes ?? []) set.add(kindGroup(n.kind));
    return Array.from(set);
  }, [data]);

  return (
    <div className="map-wrap">
      {err && <p className="error" role="alert">{err}</p>}
      {!data ? <p className="muted">Cargando mapa…</p>
        : data.nodes.length < 2 ? (
          <div className="map-empty">
            <p className="muted">El mapa necesita al menos dos documentos listos para calcular relaciones entre ellos.</p>
            <button className="primary small" onClick={onGoUpload}>Subir documento</button>
          </div>
        ) : (
          <>
            <div className="row wrap map-path-picker">
              <label className="inline">Desde
                <select value={fromId} onChange={(e) => setFromId(e.target.value)}>
                  <option value="">Elige un documento</option>
                  {data.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                </select>
              </label>
              <label className="inline">Hasta
                <select value={toId} onChange={(e) => setToId(e.target.value)}>
                  <option value="">Elige un documento</option>
                  {data.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                </select>
              </label>
              <button className="ghost small" disabled={!fromId || !toId || fromId === toId}
                onClick={() => setPath(bfsPath(data.edges, fromId, toId))}>Trazar camino</button>
              {path !== undefined && (
                path === null
                  ? <span className="muted small-text">No están conectados en el mapa.</span>
                  : <button className="ghost small" onClick={() => { setFromId(""); setToId(""); }}>Limpiar camino</button>
              )}
            </div>
            {path && (
              <ol className="map-path-result">
                {path.map((id) => <li key={id}>{byNodeId.get(id)?.name ?? id}</li>)}
              </ol>
            )}
            <div className="map-canvas-wrap" ref={wrapRef}>
              <canvas ref={canvasRef} aria-hidden="true" />
            </div>
            <div className="row wrap map-legend">
              {groupsPresent.map((g) => <span key={g} className={`pill pill-${g}`}><i aria-hidden="true" />{GROUP_LABEL[g]}</span>)}
            </div>
            <details className="details map-list">
              <summary>Documentos y relaciones ({data.nodes.length})</summary>
              <ul className="map-node-list">
                {data.nodes.map((n) => {
                  const nb = neighborsOf(n.id);
                  return (
                    <li key={n.id}>
                      <button className="ghost small" aria-pressed={selectedId === n.id} onClick={() => onSelect(n.id)}>{n.name}</button>{" "}
                      <span className="muted small-text">{GROUP_LABEL[kindGroup(n.kind)]}, {n.chunks} fragmentos</span>
                      {nb.length > 0 && (
                        <ul className="map-neighbor-list">
                          {nb.map((x) => (
                            <li key={x.id}>
                              <button className="ghost small" onClick={() => onSelect(x.id)}>{x.name}</button>{" "}
                              <span className="muted small-text">{Math.round(x.similarity * 100)}%</span>
                            </li>))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            </details>
          </>
        )}
      {selectedDoc && (
        <DocDetail
          doc={selectedDoc}
          confirming={confirm === selectedDoc.document_id}
          onAskDelete={() => onAskDelete(selectedDoc.document_id)}
          onConfirmDelete={() => onConfirmDelete(selectedDoc.document_id)}
          onCancelDelete={onCancelDelete}
          onCancelProcessing={() => onCancelProcessing(selectedDoc.document_id)}
          onClose={() => onSelect(null)}
          neighbors={selectedNode ? neighborsOf(selectedNode.id) : undefined}
          onSelectNeighbor={onSelect}
        />
      )}
    </div>
  );
}
