from __future__ import annotations

import sqlite3
import time

from packages.schemas.models import Privacy, Source, Verification
from services.rag.qdrant import Qdrant

TOP_K = 5
MIN_SCORE = 0.45


async def retrieve(con: sqlite3.Connection, qdrant: Qdrant, embed, query: str, owner: str,
                   document_ids: list[str] | None = None) -> tuple[list[dict], list[Source], float]:
    """Authorization filter first (owner + ready docs), then vector search. Returns (chunks, sources, seconds)."""
    t0 = time.perf_counter()
    allowed = {r["document_id"]: dict(r) for r in con.execute(
        "SELECT * FROM documents WHERE owner=? AND status='ready' AND kind IN ('pdf','markdown','text')", (owner,))}
    ids = [d for d in (document_ids or allowed.keys()) if d in allowed]
    if not ids:
        return [], [], time.perf_counter() - t0
    vec = (await embed([query]))[0]
    hits = await qdrant.search(vec, TOP_K, ids)
    chunks, sources, seen = [], [], set()
    for h in hits:
        if h["score"] < MIN_SCORE:
            continue
        p = h["payload"]
        row = con.execute("SELECT text FROM chunks WHERE chunk_id=?", (h["id"],)).fetchone()
        if not row:
            continue
        doc = allowed[p["document_id"]]
        chunks.append({"n": len(chunks) + 1, "document_id": p["document_id"], "name": doc["original_name"],
                       "location": p["location"], "text": row["text"], "score": round(h["score"], 3),
                       "privacy": doc["privacy"]})
        key = (p["document_id"], p["location"])
        if key not in seen:
            seen.add(key)
            sources.append(Source(kind="document", title=doc["original_name"], location=p["location"],
                                  url=f"/api/documents/{p['document_id']}/file", privacy=Privacy(doc["privacy"]),
                                  verification=Verification(doc["verification"])))
    return chunks, sources, time.perf_counter() - t0
