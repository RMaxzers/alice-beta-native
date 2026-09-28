import { useEffect, useRef } from "react";
import { Logo, type LogoState } from "../Logo";
import { reducedMotion } from "./Network";

// The fisheye portal: a circular lens with a radial burst of light streaks (mostly teal, a few
// gold/copper), a few slowly rotating gold/teal orbit rings, and sparse star sparkles. Canvas 2D
// only (no WebGL), capped fps and streak count to stay light on a laptop GPU. The container's own
// border-radius + overflow:hidden clips the circle, so the canvas itself never needs to clip.
const FPS = 30;
const FRAME_MS = 1000 / FPS;
const N_STREAKS = 240;
const N_STARS = 46;
const LOGO_SIZE = 96;

interface Streak { angle: number; speed: number; len: number; width: number; phase: number; hue: 0 | 1 | 2 }
interface Star { angle: number; dist: number; r: number; tw: number }

// Deterministic seeded RNG (mulberry-ish) — no dependency needed for a fixed decorative field.
function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 0xffffffff; };
}

function makeStreaks(n: number): Streak[] {
  const rnd = rng(20260928);
  return Array.from({ length: n }, () => ({
    angle: rnd() * Math.PI * 2,
    speed: 0.35 + rnd() * 0.55,
    len: 0.16 + rnd() * 0.22,
    width: 0.6 + rnd() * 1.2,
    phase: rnd(),
    hue: rnd() < 0.78 ? 0 : rnd() < 0.5 ? 1 : 2, // mostly teal, a few gold, a few copper
  }));
}
function makeStars(n: number): Star[] {
  const rnd = rng(70319);
  return Array.from({ length: n }, () => ({ angle: rnd() * Math.PI * 2, dist: 0.14 + rnd() * 0.86, r: 0.5 + rnd() * 1.1, tw: rnd() * Math.PI * 2 }));
}
const STREAKS = makeStreaks(N_STREAKS);
const STARS = makeStars(N_STARS);
const RINGS: [rx: number, ry: number, w: number, hue: 0 | 1][] = [
  [0.86, 0.30, 0.00020, 1], [0.68, 0.22, -0.00015, 0], [0.50, 0.16, 0.00026, 1],
];

interface Colors { accent: string; gold: string; copper: string; text: string; danger: string }

function readColors(el: Element): Colors {
  const cs = getComputedStyle(el);
  const v = (name: string) => cs.getPropertyValue(name).trim();
  return { accent: v("--accent"), gold: v("--accent-2"), copper: v("--route-cloud"), text: v("--text"), danger: v("--danger") };
}

// Tokens are always "#rrggbb" (theme.css) — no general CSS color parsing needed.
function hexAlpha(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

function hue(colors: Colors, h: 0 | 1 | 2) { return h === 0 ? colors.accent : h === 1 ? colors.gold : colors.copper; }

function draw(ctx: CanvasRenderingContext2D, size: number, dpr: number, colors: Colors, t: number, boosting: boolean, flashing: boolean) {
  const W = size * dpr, cx = W / 2, cy = W / 2, R = W / 2;
  ctx.clearRect(0, 0, W, W);

  const glowR = R * (boosting ? 0.62 : 0.48);
  const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
  glow.addColorStop(0, hexAlpha(colors.accent, boosting ? 0.30 : 0.16));
  glow.addColorStop(1, hexAlpha(colors.accent, 0));
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, W);

  const speedMul = boosting ? 2.6 : 1;
  const innerR = R * 0.16;
  for (const s of STREAKS) {
    const prog = (s.phase + t * 0.00012 * s.speed * speedMul) % 1;
    const r0 = innerR + prog * (R - innerR);
    const r1 = Math.min(R, r0 + s.len * R);
    const cosA = Math.cos(s.angle), sinA = Math.sin(s.angle);
    const alpha = Math.sin(prog * Math.PI) * 0.6 + 0.05;
    ctx.strokeStyle = hexAlpha(hue(colors, s.hue), alpha);
    ctx.lineWidth = s.width * dpr * (boosting ? 1.4 : 1);
    ctx.beginPath();
    ctx.moveTo(cx + cosA * r0, cy + sinA * r0);
    ctx.lineTo(cx + cosA * r1, cy + sinA * r1);
    ctx.stroke();
  }

  for (const [rx, ry, w, h] of RINGS) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(t * w);
    ctx.strokeStyle = hexAlpha(hue(colors, h), 0.4);
    ctx.lineWidth = 1.1 * dpr;
    ctx.beginPath();
    ctx.ellipse(0, 0, R * rx, R * ry, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  for (const st of STARS) {
    const x = cx + Math.cos(st.angle) * st.dist * R, y = cy + Math.sin(st.angle) * st.dist * R;
    const tw = 0.35 + 0.65 * Math.abs(Math.sin(t * 0.001 + st.tw));
    ctx.fillStyle = hexAlpha(colors.text, tw * 0.55);
    ctx.beginPath();
    ctx.arc(x, y, st.r * dpr, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.beginPath();
  ctx.arc(cx, cy, R - 1.5 * dpr, 0, Math.PI * 2);
  ctx.lineWidth = 2 * dpr;
  ctx.strokeStyle = flashing ? colors.danger : hexAlpha(colors.accent, 0.85);
  ctx.stroke();
}

export function Portal({ state = "idle", boostKey = 0, errorKey = 0 }: { state?: LogoState; boostKey?: number; errorKey?: number }) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const boostUntil = useRef(0);
  const errorUntil = useRef(0);

  // Submit answers with a brief acceleration of the streaks; an error flashes the lens ring once.
  useEffect(() => { if (boostKey > 0) boostUntil.current = performance.now() + 900; }, [boostKey]);
  useEffect(() => { if (errorKey > 0) errorUntil.current = performance.now() + 520; }, [errorKey]);

  useEffect(() => {
    const box = wrap.current, el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!box || !el || !ctx) return;

    if (reducedMotion()) {
      const dpr = Math.min(devicePixelRatio || 1, 2), size = box.clientWidth || 1;
      el.width = Math.round(size * dpr); el.height = Math.round(size * dpr);
      draw(ctx, size, dpr, readColors(el), 0, false, false);
      return;
    }

    let colors = readColors(el);
    let dpr = Math.min(devicePixelRatio || 1, 2);
    let size = box.clientWidth || 1;

    function resize() {
      size = box!.clientWidth || 1;
      dpr = Math.min(devicePixelRatio || 1, 2);
      el!.width = Math.round(size * dpr); el!.height = Math.round(size * dpr);
      colors = readColors(el!);
    }
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(box);

    const mq = matchMedia("(prefers-color-scheme: light)");
    const onScheme = () => { colors = readColors(el!); };
    mq.addEventListener("change", onScheme);

    let raf = 0, last = 0;
    function loop(t: number) {
      if (t - last >= FRAME_MS) {
        last = t;
        draw(ctx!, size, dpr, colors, t, t < boostUntil.current, t < errorUntil.current);
      }
      raf = requestAnimationFrame(loop);
    }
    function onVis() {
      cancelAnimationFrame(raf);
      if (!document.hidden) { last = 0; raf = requestAnimationFrame(loop); }
    }
    document.addEventListener("visibilitychange", onVis);
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mq.removeEventListener("change", onScheme);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  return (
    <div className="lp-portal" ref={wrap} aria-hidden="true">
      <canvas ref={canvas} className="lp-portal-cv" />
      <div className="lp-portal-core"><Logo state={state} size={LOGO_SIZE} /></div>
    </div>
  );
}
