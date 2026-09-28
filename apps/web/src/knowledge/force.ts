// Pure force-directed layout + graph algorithms for the knowledge map.
// No React, no DOM: safe to run once synchronously (prefers-reduced-motion) or once per animation
// frame, and easy to reason about in isolation.

export type SimNode = { id: string; x: number; y: number; vx: number; vy: number; r: number };
export type SimEdge = { source: string; target: string; similarity: number };

// ponytail: plain O(n^2) repulsion. Fine for a personal knowledge base (tens of documents); switch to
// a quadtree/Barnes-Hut if node counts ever reach the thousands.
const REPEL = 2600;
const SPRING = 0.02;
const REST_LEN = 130;
const CENTER_PULL = 0.012;
const DAMPING = 0.82;

/** Advance the simulation by one tick, mutating node positions/velocities in place.
 *  Returns total displacement this tick — use it to detect when the layout has settled. */
export function stepForce(nodes: SimNode[], edges: SimEdge[], width: number, height: number): number {
  const cx = width / 2, cy = height / 2;
  const byId = new Map(nodes.map((n) => [n.id, n]));

  for (const n of nodes) {
    n.vx += (cx - n.x) * CENTER_PULL;
    n.vy += (cy - n.y) * CENTER_PULL;
  }

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) { dx = 0.5 - Math.random(); dy = 0.5 - Math.random(); d2 = dx * dx + dy * dy || 1; }
      const d = Math.sqrt(d2);
      const f = REPEL / d2;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }
  }

  for (const e of edges) {
    const a = byId.get(e.source), b = byId.get(e.target);
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 1;
    const targetLen = REST_LEN * (1.5 - e.similarity); // more similar documents rest closer together
    const f = (d - targetLen) * SPRING;
    const fx = (dx / d) * f, fy = (dy / d) * f;
    a.vx += fx; a.vy += fy;
    b.vx -= fx; b.vy -= fy;
  }

  let disp = 0;
  for (const n of nodes) {
    n.vx *= DAMPING; n.vy *= DAMPING;
    n.x += n.vx; n.y += n.vy;
    n.x = Math.max(n.r, Math.min(width - n.r, n.x));
    n.y = Math.max(n.r, Math.min(height - n.r, n.y));
    disp += Math.abs(n.vx) + Math.abs(n.vy);
  }
  return disp;
}

/** Run the simulation synchronously for a fixed number of ticks — the prefers-reduced-motion path. */
export function layoutStatic(nodes: SimNode[], edges: SimEdge[], width: number, height: number, ticks = 300): void {
  for (let i = 0; i < ticks; i++) stepForce(nodes, edges, width, height);
}

/** Deterministic starting positions on a circle, so the simulation converges the same way each load. */
export function seedCircle(nodes: SimNode[], width: number, height: number): void {
  const cx = width / 2, cy = height / 2, r = Math.min(width, height) * 0.32;
  nodes.forEach((n, i) => {
    const a = (i / Math.max(1, nodes.length)) * Math.PI * 2;
    n.x = cx + Math.cos(a) * r; n.y = cy + Math.sin(a) * r; n.vx = 0; n.vy = 0;
  });
}

/** Shortest path between two nodes by edge count (BFS over undirected edges), or null if unreachable. */
export function bfsPath(edges: { source: string; target: string }[], sourceId: string, targetId: string): string[] | null {
  if (sourceId === targetId) return [sourceId];
  const adj = new Map<string, string[]>();
  const link = (a: string, b: string) => { const l = adj.get(a); if (l) l.push(b); else adj.set(a, [b]); };
  for (const e of edges) { link(e.source, e.target); link(e.target, e.source); }

  const prev = new Map<string, string>();
  const seen = new Set([sourceId]);
  const queue = [sourceId];
  for (let i = 0; i < queue.length; i++) {
    const cur = queue[i];
    if (cur === targetId) break;
    for (const next of adj.get(cur) ?? []) {
      if (seen.has(next)) continue;
      seen.add(next); prev.set(next, cur); queue.push(next);
    }
  }
  if (!seen.has(targetId)) return null;
  const path = [targetId];
  let cur = targetId;
  while (cur !== sourceId) { cur = prev.get(cur)!; path.push(cur); }
  return path.reverse();
}

// ponytail self-check: no test runner is wired up for apps/web, so this catches a broken bfsPath/stepForce
// regression the moment the dev server evaluates the module, without adding a test framework.
if (import.meta.env?.DEV) {
  const edges = [{ source: "a", target: "b", similarity: 0.5 }, { source: "b", target: "c", similarity: 0.9 }];
  console.assert(JSON.stringify(bfsPath(edges, "a", "c")) === JSON.stringify(["a", "b", "c"]), "knowledge/force: bfsPath sequence is broken");
  console.assert(bfsPath(edges, "a", "z") === null, "knowledge/force: bfsPath should return null when unreachable");
  console.assert(bfsPath(edges, "a", "a")?.length === 1, "knowledge/force: bfsPath same-node case is broken");
  const nodes: SimNode[] = [{ id: "a", x: 0, y: 0, vx: 0, vy: 0, r: 8 }, { id: "b", x: 500, y: 0, vx: 0, vy: 0, r: 8 }];
  layoutStatic(nodes, [{ source: "a", target: "b", similarity: 1 }], 400, 300, 50);
  console.assert(Number.isFinite(nodes[0].x) && Number.isFinite(nodes[1].x), "knowledge/force: stepForce produced non-finite positions");
}
