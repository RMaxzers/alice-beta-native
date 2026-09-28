// Órbita view: the cat rides at the center, documents drift around it on rings grouped by kind.
// Items are real <button>s (DOM position updated imperatively for the slow rotation, so tab order
// and click targets stay native) — never canvas — which is what keeps this keyboard- and
// screen-reader-accessible without a separate fallback.
import { useEffect, useMemo, useRef } from "react";
import { Logo } from "../Logo";
import { DocDetail } from "./DocDetail";
import { GROUP_LABEL, kindGroup, reducedMotion, type Doc, type DocActions, type KindGroup } from "./shared";

const FPS = 30;
const FRAME_MS = 1000 / FPS;
const REV_MS = 130_000; // one revolution every ~2.2 minutes, under the "≤ 1 rev / 2 min" cap

type RingSpec = { rx: number; ry: number; groups: KindGroup[] };
// Innermost ring: PDFs. Middle: text & markdown. Outer: spreadsheets and logs share the ring, split
// by arc. Flattened ellipses echo the tunnel-of-light rings already used in the landing Portal.
const RINGS: RingSpec[] = [
  { rx: 0.16, ry: 0.11, groups: ["pdf"] },
  { rx: 0.34, ry: 0.20, groups: ["texto"] },
  { rx: 0.48, ry: 0.29, groups: ["hojas", "logs", "otros"] },
];

interface Placed { rx: number; ry: number; angle: number }

function layoutOrbit(docs: Doc[]): Map<string, Placed> {
  const byGroup = new Map<KindGroup, Doc[]>();
  for (const d of docs) {
    const g = kindGroup(d.kind);
    const bucket = byGroup.get(g);
    if (bucket) bucket.push(d); else byGroup.set(g, [d]);
  }
  const pos = new Map<string, Placed>();
  for (const ring of RINGS) {
    const present = ring.groups.filter((g) => (byGroup.get(g)?.length ?? 0) > 0);
    const total = present.reduce((s, g) => s + (byGroup.get(g)?.length ?? 0), 0);
    if (total === 0) continue;
    let angleStart = -Math.PI / 2;
    for (const g of present) {
      const items = byGroup.get(g)!.slice().sort((a, b) => a.document_id.localeCompare(b.document_id));
      const arc = (items.length / total) * Math.PI * 2;
      items.forEach((doc, i) => {
        const angle = angleStart + (arc * (i + 0.5)) / items.length;
        pos.set(doc.document_id, { rx: ring.rx, ry: ring.ry, angle });
      });
      angleStart += arc;
    }
  }
  return pos;
}

function place(el: HTMLButtonElement, p: Placed, rot: number) {
  const a = p.angle + rot;
  el.style.left = `${50 + p.rx * 100 * Math.cos(a)}%`;
  el.style.top = `${50 + p.ry * 100 * Math.sin(a)}%`;
}

export function Orbit({ docs, q, selectedId, onSelect, confirm, onAskDelete, onConfirmDelete, onCancelDelete, onCancelProcessing }: {
  docs: Doc[]; q: string; selectedId: string | null; onSelect: (id: string | null) => void;
} & DocActions) {
  const visible = useMemo(
    () => docs.filter((d) => d.original_name.toLowerCase().includes(q.toLowerCase())),
    [docs, q],
  );
  const layout = useMemo(() => layoutOrbit(visible), [visible]);
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());
  const pausedRef = useRef(false);

  useEffect(() => {
    if (reducedMotion()) return; // items already render at rot=0 below; nothing left to animate
    let raf = 0, last = 0;
    const start = performance.now();
    function tick(t: number) {
      if (!pausedRef.current && t - last >= FRAME_MS) {
        last = t;
        const rot = ((t - start) / REV_MS) * Math.PI * 2;
        for (const [id, p] of layout) {
          const el = itemRefs.current.get(id);
          if (el) place(el, p, rot);
        }
      }
      raf = requestAnimationFrame(tick);
    }
    function onVis() {
      cancelAnimationFrame(raf);
      if (!document.hidden) { last = 0; raf = requestAnimationFrame(tick); }
    }
    document.addEventListener("visibilitychange", onVis);
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); document.removeEventListener("visibilitychange", onVis); };
  }, [layout]);

  const selectedDoc = visible.find((d) => d.document_id === selectedId) ?? null;

  if (visible.length === 0) return null;

  return (
    <div className="orbit-wrap">
      <div
        className="orbit"
        onMouseEnter={() => { pausedRef.current = true; }}
        onMouseLeave={() => { pausedRef.current = false; }}
        onFocus={() => { pausedRef.current = true; }}
        onBlur={() => { pausedRef.current = false; }}
      >
        <div className="orbit-center" aria-hidden="true"><Logo state="knowledge" size={88} /></div>
        {Array.from(layout.entries()).map(([id, p]) => {
          const doc = visible.find((d) => d.document_id === id);
          if (!doc) return null;
          const initial = { left: `${50 + p.rx * 100 * Math.cos(p.angle)}%`, top: `${50 + p.ry * 100 * Math.sin(p.angle)}%` };
          return (
            <button
              key={id}
              ref={(el) => { if (el) itemRefs.current.set(id, el); else itemRefs.current.delete(id); }}
              className={`orbit-item st-${doc.status}${selectedId === id ? " is-selected" : ""}`}
              style={initial}
              onClick={() => onSelect(selectedId === id ? null : id)}
              aria-pressed={selectedId === id}
              aria-label={`${doc.original_name}, ${GROUP_LABEL[kindGroup(doc.kind)]}`}
              title={`${doc.original_name}, ${GROUP_LABEL[kindGroup(doc.kind)]}`}
            >
              <span className="orbit-dot" aria-hidden="true" />
              <span className="orbit-label">{doc.original_name}</span>
            </button>
          );
        })}
      </div>
      <p className="muted small-text orbit-legend">
        Los anillos agrupan por tipo: PDF en el interior, texto y markdown en el medio, hojas de cálculo y registros en el exterior.
        El color del punto es el estado: <span className="legend-ready">listo</span>,{" "}
        <span className="legend-warn">procesando o en cola</span>, <span className="legend-fail">fallido</span>.
      </p>
      {selectedDoc && (
        <DocDetail
          doc={selectedDoc}
          confirming={confirm === selectedDoc.document_id}
          onAskDelete={() => onAskDelete(selectedDoc.document_id)}
          onConfirmDelete={() => onConfirmDelete(selectedDoc.document_id)}
          onCancelDelete={onCancelDelete}
          onCancelProcessing={() => onCancelProcessing(selectedDoc.document_id)}
          onClose={() => onSelect(null)}
        />
      )}
    </div>
  );
}
