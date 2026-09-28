"""Document similarity graph for the Knowledge map: one centroid per document, cosine top-k neighbours."""
from __future__ import annotations

import math


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def centroid(vectors: list[list[float]]) -> list[float]:
    """Mean of the unit chunk vectors, re-normalised (so long documents don't dominate by length)."""
    units = [_unit(v) for v in vectors]
    return _unit([sum(col) / len(units) for col in zip(*units)])


def document_edges(vectors: dict[str, list[list[float]]], k: int = 3, min_sim: float = 0.55) -> list[dict]:
    """Undirected edges between documents: each keeps its k most similar neighbours above min_sim.
    ponytail: O(n²) pairwise cosine in pure Python; fine for hundreds of documents, use Qdrant recommend if it grows."""
    cents = {d: centroid(vs) for d, vs in vectors.items() if vs}
    ids = sorted(cents)
    sims: dict[tuple[str, str], float] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            sims[(a, b)] = sum(x * y for x, y in zip(cents[a], cents[b]))
    keep: set[tuple[str, str]] = set()
    for d in ids:
        mine = sorted(((s, pair) for pair, s in sims.items() if d in pair and s >= min_sim), reverse=True)[:k]
        keep.update(pair for _, pair in mine)
    return [{"source": a, "target": b, "similarity": round(max(0.0, min(1.0, sims[(a, b)])), 3)} for a, b in sorted(keep)]
