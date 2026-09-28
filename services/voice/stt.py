"""Lazy faster-whisper singleton for local speech-to-text (STT).

Runs fully on this machine (CPU, int8 by default) — no audio or transcript ever leaves it. The model is
downloaded once on first use (huggingface cache) and kept in memory for the life of the process; the actual
decode/transcribe call runs in a worker thread via asyncio.to_thread so it never blocks the event loop.
faster-whisper decodes audio with the bundled PyAV, so webm/ogg/wav straight from the browser's
MediaRecorder all work without extra conversion.
"""
from __future__ import annotations

import asyncio
import io
import threading

from faster_whisper import WhisperModel

_model: WhisperModel | None = None
_lock = threading.Lock()


def is_loaded() -> bool:
    return _model is not None


def _load(model_name: str, device: str) -> WhisperModel:
    global _model
    with _lock:
        if _model is None:
            compute_type = "int8" if device == "cpu" else "float16"
            _model = WhisperModel(model_name, device=device, compute_type=compute_type)
        return _model


def _transcribe_sync(audio: bytes, model_name: str, device: str) -> tuple[str, float | None]:
    model = _load(model_name, device)
    # ponytail: force Spanish first (Alice's UI language; more reliable on short clips than auto-detect),
    # only fall back to language auto-detect if that pass produced nothing.
    for language in ("es", None):
        segments, info = model.transcribe(io.BytesIO(audio), language=language)
        text = "".join(s.text for s in segments).strip()
        if text:
            return text, info.duration
    return "", None


async def transcribe(audio: bytes, model_name: str, device: str) -> tuple[str, float | None]:
    """Returns (text, duration_seconds); duration is None if both passes came back empty."""
    return await asyncio.to_thread(_transcribe_sync, audio, model_name, device)
