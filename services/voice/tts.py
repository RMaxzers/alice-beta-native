"""Async proxy to the local pocket-tts sidecar (Kyutai, Spanish voice model).

The sidecar binds 127.0.0.1:8010 (same loopback-only convention as Ollama/Qdrant); this module never
talks to anything else. See storage/sidecars/pocket-tts/openapi.json for the sidecar's own contract.
"""
from __future__ import annotations

import httpx


class TtsError(Exception):
    """Spanish, user-facing message: sidecar unreachable or it rejected the request."""


async def synthesize(base_url: str, text: str, voice: str | None = None, timeout: float = 30.0,
                     client: httpx.AsyncClient | None = None) -> tuple[bytes, str]:
    """Returns (audio_bytes, content_type). `client` is for tests (inject an httpx.MockTransport)."""
    data = {"text": text}
    if voice:
        data["voice_url"] = voice
    owns_client = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            r = await c.post(f"{base_url.rstrip('/')}/tts", data=data)
        except httpx.HTTPError as e:
            raise TtsError("El servicio de voz (TTS) no está disponible en este equipo.") from e
    finally:
        if owns_client:
            await c.aclose()
    if r.status_code != 200:
        raise TtsError(f"El servicio de voz respondió con un error ({r.status_code}).")
    return r.content, r.headers.get("content-type", "audio/wav")


async def check_health(base_url: str, timeout: float = 2.0, client: httpx.AsyncClient | None = None) -> bool:
    owns_client = client is None
    c = client or httpx.AsyncClient(timeout=timeout)
    try:
        r = await c.get(f"{base_url.rstrip('/')}/health")
        return r.status_code == 200
    except httpx.HTTPError:
        return False
    finally:
        if owns_client:
            await c.aclose()
