import { useEffect, useRef, type ReactNode } from "react";

// Shader orb from the Figma Make "Shader Reminder" (5A40MPUJ9ju1R2b981WqTo, "Flowing Waves"), recolored to the
// Nebulosa palette. Used as Alice's voice orb (Chat) and the reminders orb (Hoy).
// Smoothness: tint, energy and audio level are eased every frame, and the wave phase is integrated (phase += speed·dt),
// so a state change bends the motion instead of jumping. Decorative: the caller provides the accessible label/control.

export type Tint = "violet" | "cyan" | "copper";
const TINT: Record<Tint, [number, number, number]> = {
  violet: [0.62, 0.31, 0.87],  // #9d4edd
  cyan: [0.0, 0.96, 0.83],     // #00f5d4
  copper: [0.94, 0.48, 0.43],  // #f07a6e (--danger)
};

const VERT = `attribute vec2 a;varying vec2 v;void main(){v=a*.5+.5;gl_Position=vec4(a,0.,1.);}`;
const FRAG = `precision mediump float;
uniform float uPhase;uniform float uAmp;uniform vec3 uTint;uniform float uDim;varying vec2 v;
void main(){
  vec2 uv=v*2.-1.;float r=length(uv);
  float edge=1.-smoothstep(.97,1.,r);
  if(edge<=0.){gl_FragColor=vec4(0.);return;}
  vec2 p=uv*1.6;
  for(float i=1.;i<8.;i++){p.x+=uAmp/i*cos(i*2.5*p.y+uPhase);p.y+=uAmp/i*cos(i*1.5*p.x+uPhase);}
  vec3 c=min(uTint*.11/max(abs(sin(uPhase-p.y-p.x)),.04),vec3(1.4));
  c*=mix(1.,mix(.25,1.,smoothstep(.15,.6,r)),uDim);
  c+=uTint*.25*smoothstep(.75,1.,r);
  gl_FragColor=vec4(c*edge,edge);
}`;

type Props = {
  size: number;
  tint: Tint;
  energy: number;            // 0 calm … 1 busy
  level?: () => number;      // live 0..1 audio level, read every frame
  dimCenter?: boolean;       // darken the middle so children stay readable
  className?: string;
  children?: ReactNode;
};

export function Orb({ size, tint, energy, level, dimCenter = true, className = "", children }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const target = useRef({ tint: TINT[tint], energy, level });
  target.current = { tint: TINT[tint], energy, level };
  const redraw = useRef<() => void>(() => {});

  useEffect(() => {
    const canvas = ref.current;
    const gl = canvas?.getContext("webgl", { premultipliedAlpha: true, antialias: true, preserveDrawingBuffer: true }); // readable for captures
    if (!canvas || !gl) return; // CSS fallback (.orb background) stays visible
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = canvas.height = Math.round(size * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);

    const sh = (type: number, src: string) => {
      const s = gl.createShader(type)!; gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(s));
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog); gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const aLoc = gl.getAttribLocation(prog, "a");
    gl.enableVertexAttribArray(aLoc); gl.vertexAttribPointer(aLoc, 2, gl.FLOAT, false, 0, 0);
    const u = (n: string) => gl.getUniformLocation(prog, n);
    const uPhase = u("uPhase"), uAmp = u("uAmp"), uTint = u("uTint"), uDim = u("uDim");
    gl.uniform1f(uDim, dimCenter ? 1 : 0);

    const cur = { tint: [...target.current.tint], energy: target.current.energy, level: 0, phase: Math.random() * 10 };
    let raf = 0, last = performance.now(), visible = true;

    const draw = (dt: number) => {
      const t = target.current;
      const k = 1 - Math.exp(-dt * 2.5);                 // ~0.4 s to settle tint/energy
      for (let i = 0; i < 3; i++) cur.tint[i] += (t.tint[i] - cur.tint[i]) * k;
      cur.energy += (t.energy - cur.energy) * k;
      const lv = Math.min(1, Math.max(0, t.level?.() ?? 0));
      cur.level += (lv - cur.level) * (1 - Math.exp(-dt * (lv > cur.level ? 14 : 5))); // fast attack, soft release
      cur.phase += dt * (0.25 + cur.energy * 0.9 + cur.level * 1.6);
      gl.uniform1f(uPhase, cur.phase);
      gl.uniform1f(uAmp, 0.45 + cur.energy * 0.2 + cur.level * 0.35);
      gl.uniform3f(uTint, cur.tint[0], cur.tint[1], cur.tint[2]);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    const loop = (now: number) => {
      draw(Math.min(0.05, (now - last) / 1000)); last = now;
      raf = visible && !document.hidden ? requestAnimationFrame(loop) : 0;
    };
    const resume = () => { if (!still && !raf && visible && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(loop); } };
    // Reduced motion: settle instantly and draw one frame per prop change.
    redraw.current = still ? () => draw(10) : resume;

    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; resume(); });
    io.observe(canvas);
    document.addEventListener("visibilitychange", resume);
    if (still) draw(10); else resume();
    return () => {
      cancelAnimationFrame(raf); io.disconnect();
      document.removeEventListener("visibilitychange", resume);
      gl.deleteBuffer(buf); gl.deleteProgram(prog);
      redraw.current = () => {};
    };
  }, [size, dimCenter]);

  useEffect(() => { redraw.current(); }, [tint, energy]);

  return (
    <div className={`orb orb-${tint} ${className}`} style={{ width: size, height: size }}>
      <canvas ref={ref} aria-hidden="true" style={{ width: size, height: size }} />
      {children && <div className="orb-center">{children}</div>}
    </div>
  );
}
