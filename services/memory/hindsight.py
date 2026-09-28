"""Async client for the local Hindsight memory sidecar (loopback long-term memory).

One bank per Alice user (`alice-<username>`), so bank isolation IS user isolation: a memory_id that
belongs to another user's bank simply does not exist in this user's bank. Retain triggers local LLM fact
extraction (seconds on the GPU): never await it on the chat response path — see
services.workers.orchestrator._retain_async, which schedules it as a background task.

See storage/sidecars/hindsight/openapi.json for the sidecar's own contract.
"""
from __future__ import annotations

import httpx

RECALL_TIMEOUT = 1.5
DEFAULT_TIMEOUT = 10.0


class MemoryUnavailable(Exception):
    """Spanish, user-facing message: the sidecar is down, slow, or rejected the request."""


def bank_id(username: str) -> str:
    return f"alice-{username}"


def _url(base_url: str, bank: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/v1/default/banks/{bank}/{path}"


async def _request(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    try:
        r = await client.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise MemoryUnavailable("La memoria local no está disponible en este momento.") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001 — body isn't JSON or has no "detail"; fall back to the status code
            detail = None
        raise MemoryUnavailable(detail or f"La memoria local respondió con un error ({r.status_code}).")
    return r


async def health(base_url: str, timeout: float = 2.0, client: httpx.AsyncClient | None = None) -> bool:
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        r = await c.get(f"{base_url.rstrip('/')}/health")
        return r.status_code == 200
    except httpx.HTTPError:
        return False
    finally:
        if owns:
            await c.aclose()


async def recall(base_url: str, username: str, query: str, limit: int = 5, timeout: float = RECALL_TIMEOUT,
                 client: httpx.AsyncClient | None = None) -> list[dict]:
    """Top `limit` memories for this user's message. Raises MemoryUnavailable on timeout/error/down —
    callers on the chat path must catch it and skip memory rather than fail the answer."""
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        r = await _request(c, "POST", _url(base_url, bank_id(username), "memories/recall"),
                           json={"query": query, "budget": "low", "include": {"entities": None}})
    finally:
        if owns:
            await c.aclose()
    return r.json().get("results", [])[:limit]


async def retain(base_url: str, username: str, content: str, *, context: str = "chat", timestamp: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT, client: httpx.AsyncClient | None = None) -> None:
    """Retain one item. `async=True` on the sidecar side so it only enqueues extraction instead of running
    the (slow) local-LLM fact extraction inline. Callers must still run this in a background task themselves
    (see orchestrator._retain_async) — this function still waits for the HTTP round trip to complete."""
    item = {"content": content, "context": context}
    if timestamp:
        item["timestamp"] = timestamp
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        await _request(c, "POST", _url(base_url, bank_id(username), "memories"), json={"items": [item], "async": True})
    finally:
        if owns:
            await c.aclose()


async def list_memories(base_url: str, username: str, q: str | None = None, limit: int = 50, offset: int = 0,
                        timeout: float = DEFAULT_TIMEOUT, client: httpx.AsyncClient | None = None) -> dict:
    params: dict = {"limit": limit, "offset": offset}
    if q:
        params["q"] = q
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        r = await _request(c, "GET", _url(base_url, bank_id(username), "memories/list"), params=params)
    finally:
        if owns:
            await c.aclose()
    return r.json()


async def forget(base_url: str, username: str, memory_id: str, reason: str = "olvidado por el usuario",
                 timeout: float = DEFAULT_TIMEOUT, client: httpx.AsyncClient | None = None) -> None:
    """Soft-delete (reversible): marks the memory 'invalidated' in the user's own bank instead of erasing it.

    ponytail: only 'world'/'experience' facts can be curated this way; an 'observation' (a fact derived and
    consolidated from others) is rejected by the sidecar with 400 ("observations are derived and regenerate
    from their sources") — the caller sees that as MemoryUnavailable. Forgetting the underlying source facts
    (their ids are in the observation's `source_memory_ids`) is the real fix; not implemented in this beta.
    """
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        await _request(c, "PATCH", _url(base_url, bank_id(username), f"memories/{memory_id}"),
                       json={"state": "invalidated", "reason": reason})
    finally:
        if owns:
            await c.aclose()
