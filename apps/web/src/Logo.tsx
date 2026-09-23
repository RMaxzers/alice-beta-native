export type LogoState = "idle" | "routing" | "local" | "knowledge" | "cloud" | "observability" | "error";

export const STATE_LABEL: Record<LogoState, string> = {
  idle: "En espera", routing: "Decidiendo ruta", local: "Modelo local", knowledge: "Consultando conocimiento",
  cloud: "Salida externa", observability: "Telemetría", error: "Error",
};

// Core orb with six route nodes. The active state picks color and which connections pulse (CSS in styles.css).
const NODES: [number, number, string][] = [
  [50, 10, "cloud"], [85, 30, "cloud"], [85, 70, "observability"], [50, 90, "knowledge"], [15, 70, "knowledge"], [15, 30, "local"],
];

export function Logo({ state = "idle", size = 40 }: { state?: LogoState; size?: number }) {
  return (
    <svg className="logo" data-state={state} width={size} height={size} viewBox="0 0 100 100" role="img"
      aria-label={`Alice: ${STATE_LABEL[state]}`}>
      <circle className="orbit" cx="50" cy="50" r="40" />
      <g className="links">
        {NODES.map(([x, y, k], i) => (
          <line key={i} x1="50" y1="50" x2={x} y2={y} data-k={k} style={{ animationDelay: `${i * 0.18}s` }} />
        ))}
      </g>
      <g className="nodes">
        {NODES.map(([x, y, k], i) => <circle key={i} cx={x} cy={y} r="5" data-k={k} />)}
      </g>
      <circle className="halo" cx="50" cy="50" r="24" />
      <circle className="core" cx="50" cy="50" r="17" />
      <circle className="eye" cx="50" cy="50" r="7" />
    </svg>
  );
}
