import { useId } from "react";
import "./logo.css";

export type LogoState = "idle" | "routing" | "local" | "knowledge" | "cloud" | "observability" | "error";

export const STATE_LABEL: Record<LogoState, string> = {
  idle: "En espera", routing: "Decidiendo ruta", local: "Modelo local", knowledge: "Consultando conocimiento",
  cloud: "Salida externa", observability: "Telemetría", error: "Error",
};

// Alice: a helmeted cat seen through a fisheye lens, riding a tunnel of light.
// The ring, the speed lines, the visor rivets and the eye glints take the route color (--c, logo.css).
// Original vector; useId keeps the gradient id unique when several logos share a page.

export function Logo({ state = "idle", size = 40 }: { state?: LogoState; size?: number }) {
  const g = `alice-lens${useId().replace(/:/g, "")}`;
  return (
    <svg className="logo" data-state={state} width={size} height={size} viewBox="0 0 100 100" role="img"
      aria-label={`Alice: ${STATE_LABEL[state]}`}>
      <defs>
        <radialGradient id={g} cx="50%" cy="42%" r="58%">
          <stop offset="0" className="lens-glow" stopOpacity=".42" />
          <stop offset=".7" className="lens-glow" stopOpacity=".08" />
          <stop offset="1" stopColor="#000" />
        </radialGradient>
      </defs>
      <circle className="lens" cx="50" cy="50" r="47" fill={`url(#${g})`} />
      <g className="speed">
        <line x1="8" y1="44" x2="19" y2="46" /><line x1="10" y1="62" x2="20" y2="59" />
        <line x1="92" y1="44" x2="81" y2="46" /><line x1="90" y1="62" x2="80" y2="59" />
        <line x1="24" y1="12" x2="30" y2="21" /><line x1="76" y1="12" x2="70" y2="21" /><line x1="50" y1="5" x2="50" y2="12" />
      </g>
      <g className="cat">
        <path className="face" d="M22 58C18 74 32 90 50 90C68 90 82 74 78 58Z" />
        <path className="helmet" d="M28 50C28 22 72 22 72 50Z" />
        <path className="shine" d="M33 40C35 29 44 25 50 25" />
        <rect className="rim" x="24" y="47" width="52" height="9" rx="4.5" />
        <circle className="rivet" cx="31" cy="51.5" r="1.6" /><circle className="rivet" cx="69" cy="51.5" r="1.6" />
        <g className="eyes">
          <path d="M33 65q7-5 14 0q-7 3.5-14 0Z" /><path d="M53 65q7-5 14 0q-7 3.5-14 0Z" />
        </g>
        <circle className="glint" cx="42" cy="64.3" r="1.1" /><circle className="glint" cx="62" cy="64.3" r="1.1" />
        <path className="nose" d="M45.5 72h9l-4.5 5z" />
        <path className="mouth" d="M50 77v2.5M45 81q5 2.5 10 0" />
      </g>
      <circle className="ring" cx="50" cy="50" r="47" />
    </svg>
  );
}
