"""Voice: speech-to-text for the composer, text-to-speech for finished answers.

Both directions stay on this machine: STT runs faster-whisper locally (services/voice/stt.py), TTS proxies
to the pocket-tts sidecar on settings.tts_url (127.0.0.1:8010 by default, services/voice/tts.py). Nothing
here makes an outbound network call.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from apps.api.security import require_user
from services.voice import stt as stt_service
from services.voice import tts as tts_service

router = APIRouter()

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
MAX_TTS_CHARS = 2000


def _settings(request: Request):
    return request.app.state.alice.settings


@router.get("/api/voice/status")
async def voice_status(request: Request, user: str = Depends(require_user)):
    s = _settings(request)
    reachable = await tts_service.check_health(s.tts_url) if s.voice_enabled else False
    return {"enabled": s.voice_enabled, "tts": {"reachable": reachable},
            "stt": {"model": s.stt_model, "device": s.stt_device, "loaded": stt_service.is_loaded()}}


@router.post("/api/voice/stt")
async def voice_stt(request: Request, audio: UploadFile = File(...), user: str = Depends(require_user)):
    s = _settings(request)
    if not s.voice_enabled:
        raise HTTPException(503, "La voz está deshabilitada en este equipo.")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(422, "No se recibió audio.")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "El audio supera el tamaño máximo (10 MB).")
    try:
        text, duration = await stt_service.transcribe(data, s.stt_model, s.stt_device)
    except Exception as e:  # noqa: BLE001 — any decode/model failure maps to the same user-facing message
        raise HTTPException(422, "No se pudo procesar el audio (formato no compatible o archivo dañado).") from e
    # ponytail: duration is only known after transcribing (faster-whisper reports it); a pre-decode probe
    # (open the container, read the header only) would reject oversized clips earlier if this gets costly.
    if duration is not None and duration > MAX_AUDIO_SECONDS:
        raise HTTPException(413, "El audio supera la duración máxima (60 s).")
    return {"text": text}


class TtsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    voice: str | None = None


@router.post("/api/voice/tts")
async def voice_tts(body: TtsIn, request: Request, user: str = Depends(require_user)):
    s = _settings(request)
    if not s.voice_enabled:
        raise HTTPException(503, "La voz está deshabilitada en este equipo.")
    try:
        audio, content_type = await tts_service.synthesize(s.tts_url, body.text, body.voice)
    except tts_service.TtsError as e:
        raise HTTPException(503, str(e)) from e
    return Response(content=audio, media_type=content_type)
