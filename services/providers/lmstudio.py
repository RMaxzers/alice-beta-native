"""LM Studio on loopback, optionally reached through a private SSH reverse tunnel."""
from __future__ import annotations

import ipaddress
import json
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

from services.providers.base import Chunk, Health, ProviderError, Usage


class LMStudioProvider:
    name = "lmstudio"
    local = True

    def __init__(self, base_url: str, api_token: str = "", timeout: float = 180.0):
        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if (not loopback or parsed.scheme not in ("http", "https")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("LMSTUDIO_BASE_URL debe ser una URL HTTP loopback sin ruta ni credenciales")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}

    async def _get_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=5, headers=self._headers) as client:
            response = await client.get(f"{self.base_url}/api/v1/models")
            response.raise_for_status()
            return response.json()["models"]

    async def health(self) -> Health:
        try:
            models = await self._get_models()
            return Health("healthy", f"LM Studio: {len(models)} modelos disponibles")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return Health("unavailable", type(exc).__name__)

    async def tags(self) -> list[dict]:
        return [{"name": item["key"], "size": item.get("size_bytes")}
                for item in await self._get_models()]

    async def running(self) -> list[dict]:
        # This API reports loaded instances, not measured GPU allocation.
        rows = []
        for item in await self._get_models():
            if item.get("loaded_instances"):
                rows.append({"name": item["key"], "size": item.get("size_bytes"), "size_vram": None})
                for instance in item["loaded_instances"]:
                    if instance["id"] != item["key"]:
                        rows.append({"name": instance["id"], "size": item.get("size_bytes"), "size_vram": None})
        return rows

    @staticmethod
    def _options(options: dict) -> dict:
        # Context length is set when loading the model; num_ctx is an Ollama option.
        return {key: options[key] for key in ("temperature", "top_p", "max_tokens", "stop", "seed")
                if key in options}

    async def _post(self, path: str, body: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
                response = await client.post(f"{self.base_url}{path}", json=body)
                if response.status_code != 200:
                    raise ProviderError("lmstudio_error", f"LM Studio respondió HTTP {response.status_code}")
                return response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("lmstudio_unavailable", type(exc).__name__, retryable=True) from exc

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = await self._post("/v1/embeddings", {"model": model, "input": texts})
        rows = sorted(data["data"], key=lambda item: item["index"])
        if [row["index"] for row in rows] != list(range(len(texts))):
            raise ProviderError("embed_failed", "LM Studio devolvió índices de embeddings incompletos")
        return [row["embedding"] for row in rows]

    async def complete_json(self, model: str, messages: list[dict], schema: dict, options: dict) -> str:
        data = await self._post("/v1/chat/completions", {
            "model": model, "messages": messages, "stream": False, **self._options(options),
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "alice_response", "schema": schema, "strict": True}},
        })
        content = data["choices"][0]["message"].get("content")
        if not isinstance(content, str):
            raise ProviderError("lmstudio_error", "LM Studio no devolvió contenido estructurado")
        return content

    async def stream(self, model: str, messages: list[dict], options: dict, clearance=None) -> AsyncIterator[Chunk]:
        body = {"model": model, "messages": messages, "stream": True,
                "stream_options": {"include_usage": True}, **self._options(options)}
        usage = Usage(cost_usd=0.0)
        ended = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=5), headers=self._headers) as client:
                async with client.stream("POST", f"{self.base_url}/v1/chat/completions", json=body) as response:
                    if response.status_code != 200:
                        raise ProviderError("lmstudio_error", f"LM Studio respondió HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            ended = True
                            break
                        data = json.loads(payload)
                        if "error" in data:
                            raise ProviderError("lmstudio_error", "LM Studio interrumpió la generación")
                        if data.get("usage"):
                            reported = data["usage"]
                            usage = Usage(reported.get("prompt_tokens"), reported.get("completion_tokens"), 0.0)
                        for choice in data.get("choices", []):
                            ended = ended or choice.get("finish_reason") is not None
                            content = (choice.get("delta") or {}).get("content")
                            if content:
                                yield Chunk(text=content)
            if not ended:
                raise ProviderError("lmstudio_incomplete", "LM Studio cerró la respuesta antes de completarla")
            yield Chunk(done=True, usage=usage)
        except httpx.HTTPError as exc:
            raise ProviderError("lmstudio_unavailable", type(exc).__name__, retryable=True) from exc
