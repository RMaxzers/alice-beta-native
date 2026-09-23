"""Minimal Qdrant REST client (loopback only)."""
from __future__ import annotations

import httpx

COLLECTION = "alice_chunks"


class Qdrant:
    def __init__(self, url: str, collection: str = COLLECTION):
        self.url = url.rstrip("/")
        self.collection = collection

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                return (await c.get(f"{self.url}/healthz")).status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure_collection(self, dim: int) -> None:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.url}/collections/{self.collection}")
            if r.status_code == 200:
                have = r.json()["result"]["config"]["params"]["vectors"]["size"]
                if have != dim:
                    raise RuntimeError(f"Colección con dimensión {have} != {dim}: reindexar explícitamente")
                return
            r = await c.put(f"{self.url}/collections/{self.collection}", json={"vectors": {"size": dim, "distance": "Cosine"}})
            r.raise_for_status()
            for field in ("document_id", "privacy"):
                await c.put(f"{self.url}/collections/{self.collection}/index",
                            json={"field_name": field, "field_schema": "keyword"})

    async def upsert(self, points: list[dict]) -> None:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.put(f"{self.url}/collections/{self.collection}/points?wait=true", json={"points": points})
            r.raise_for_status()

    async def search(self, vector: list[float], limit: int, document_ids: list[str] | None = None) -> list[dict]:
        flt = {"must": [{"key": "document_id", "match": {"any": document_ids}}]} if document_ids else None
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{self.url}/collections/{self.collection}/points/query",
                             json={"query": vector, "limit": limit, "with_payload": True, **({"filter": flt} if flt else {})})
            r.raise_for_status()
            return r.json()["result"]["points"]

    async def delete_document(self, document_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.url}/collections/{self.collection}/points/delete?wait=true",
                             json={"filter": {"must": [{"key": "document_id", "match": {"value": document_id}}]}})
            if r.status_code != 404:
                r.raise_for_status()

    async def snapshot(self) -> dict:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{self.url}/collections/{self.collection}/snapshots?wait=true")
            r.raise_for_status()
            return r.json()["result"]
