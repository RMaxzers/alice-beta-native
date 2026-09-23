from __future__ import annotations

import ipaddress
import json
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

from services.providers.base import Chunk, Health, ProviderError, Usage


class OllamaProvider:
    name = "ollama"
    local = True

    def __init__(self, base_url: str, timeout: float = 180.0):
        # Local routes, classifier and embeddings must run on this host: refuse any non-loopback endpoint (§8.2, §21.2-4).
        host = (urlparse(base_url).hostname or "").lower()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise ValueError(f"OLLAMA_BASE_URL debe ser loopback (127.0.0.1/localhost/::1), no {host!r}")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health(self) -> Health:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                v = (await c.get(f"{self.base_url}/api/version")).json()["version"]
            return Health("healthy", f"ollama {v}")
        except Exception as e:  # noqa: BLE001
            return Health("unavailable", type(e).__name__)

    async def tags(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=5) as c:
            return (await c.get(f"{self.base_url}/api/tags")).json().get("models", [])

    async def running(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=5) as c:
            return (await c.get(f"{self.base_url}/api/ps")).json().get("models", [])

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.base_url}/api/embed", json={"model": model, "input": texts})
            if r.status_code != 200:
                raise ProviderError("embed_failed", r.text[:200])
            return r.json()["embeddings"]

    async def complete_json(self, model: str, messages: list[dict], schema: dict, options: dict) -> str:
        """Non-streaming call with Ollama structured outputs (format = JSON schema)."""
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.base_url}/api/chat", json={
                "model": model, "messages": messages, "stream": False, "format": schema, "options": options,
            })
            if r.status_code != 200:
                raise ProviderError("ollama_error", r.text[:200])
            return r.json()["message"]["content"]

    async def stream(self, model: str, messages: list[dict], options: dict, clearance=None) -> AsyncIterator[Chunk]:
        # Local provider: no egress, clearance unused.
        body = {"model": model, "messages": messages, "stream": True, "options": options}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=5)) as c:
                async with c.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                    if r.status_code != 200:
                        raise ProviderError("ollama_error", (await r.aread()).decode()[:200])
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        d = json.loads(line)
                        if d.get("done"):
                            yield Chunk(done=True, usage=Usage(d.get("prompt_eval_count"), d.get("eval_count"), 0.0))
                            return
                        yield Chunk(text=d.get("message", {}).get("content", ""))
        except httpx.ConnectError as e:
            raise ProviderError("ollama_unavailable", "Ollama no responde en " + self.base_url) from e
