import { useEffect, useRef } from "react";

// "Neural galaxy" backdrop from the Figma Make (2rXOBX0dMcfcLAtM4ysNEf): drifting violet nodes, a few cyan
// cores, links between close pairs. Decorative only (aria-hidden, no pointer events).
// ponytail: O(n²) link scan, capped at MAX nodes; a spatial grid if the cap ever needs to grow.
const MAX = 110;
const LINK = 150;
const VIOLET = "157 78 221";
const CYAN = "0 245 212";

type Node = { x: number; y: number; vx: number; vy: number; r: number; core: boolean };

export function Galaxy() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, raf = 0;
    let nodes: Node[] = [];

    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      w = innerWidth; h = innerHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.min(MAX, Math.floor((w * h) / 12000));
      nodes = Array.from({ length: n }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.4, vy: (Math.random() - 0.5) * 0.4,
        r: Math.random() * 1.6 + 0.5, core: Math.random() > 0.95,
      }));
    };

    const frame = () => {
      ctx.clearRect(0, 0, w, h);
      ctx.lineWidth = 0.5;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d >= LINK) continue;
          const o = 1 - d / LINK;
          ctx.strokeStyle = a.core || b.core ? `rgb(${CYAN} / ${o * 0.5})` : `rgb(${VIOLET} / ${o * 0.3})`;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        }
      }
      for (const p of nodes) {
        if (!still) {
          p.x += p.vx; p.y += p.vy;
          if (p.x < 0 || p.x > w) p.vx = -p.vx;
          if (p.y < 0 || p.y > h) p.vy = -p.vy;
        }
        ctx.fillStyle = `rgb(${p.core ? CYAN : VIOLET})`;
        ctx.shadowBlur = p.core ? 15 : 0;
        ctx.shadowColor = ctx.fillStyle;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.core ? p.r * 2 : p.r, 0, Math.PI * 2); ctx.fill();
      }
      ctx.shadowBlur = 0;
      if (!still && !document.hidden) raf = requestAnimationFrame(frame);
    };

    const onResize = () => { resize(); if (still) frame(); };
    const onVisible = () => { cancelAnimationFrame(raf); if (!document.hidden && !still) frame(); };
    resize(); frame();
    addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return <canvas ref={ref} className="galaxy" aria-hidden="true" />;
}
