"""/api/voice/*: auth required, CSRF on POSTs, and server-side limits (size/length/text). Runs against the
real FastAPI app (tmp_path state); the TTS sidecar is a fake receiver on 127.0.0.1:8010 (net fixture) or
simply unregistered (⇒ "sidecar down" without ever touching the real one). STT never loads a real Whisper
model: services.voice.stt.transcribe is monkeypatched."""
from __future__ import annotations

import httpx
import pytest

from services.voice import stt as stt_service

SMALL_AUDIO = (b"webm-ish-bytes", "audio/webm")


def post_stt(c, headers, data=SMALL_AUDIO[0], ctype=SMALL_AUDIO[1]):
    return c.post("/api/voice/stt", files={"audio": ("clip.webm", data, ctype)}, headers=headers)


# ----------------------------------------------------------------------------- auth
@pytest.mark.parametrize("method,path", [("GET", "/api/voice/status"), ("POST", "/api/voice/tts"), ("POST", "/api/voice/stt")])
def test_voice_requires_auth(client, method, path):
    r = client.request(method, path, json={"text": "hola"} if path.endswith("tts") else None)
    assert r.status_code == 401


# ----------------------------------------------------------------------------- CSRF / origin
def test_csrf_required_on_tts(api):
    for headers in ({}, {"x-csrf-token": "wrong"}, {"x-csrf-token": api.csrf, "origin": "https://evil.example"}):
        r = api.c.post("/api/voice/tts", json={"text": "hola"}, headers=headers)
        assert r.status_code == 403


def test_csrf_required_on_stt(api):
    for headers in ({}, {"x-csrf-token": "wrong"}, {"x-csrf-token": api.csrf, "origin": "https://evil.example"}):
        assert post_stt(api.c, headers).status_code == 403


# ----------------------------------------------------------------------------- voice_enabled gate
def test_disabled_returns_503(make_state, net):
    from fastapi.testclient import TestClient
    from apps.api.main import app
    st = make_state(voice_enabled=False)
    app.state.alice = st
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    r = c.post("/api/login", json={"username": "admin", "password": "correct-horse-battery"})
    csrf = r.json()["csrf"]
    h = {"x-csrf-token": csrf}
    assert c.post("/api/voice/tts", json={"text": "hola"}, headers=h).status_code == 503
    assert post_stt(c, h).status_code == 503
    assert c.get("/api/voice/status", headers=h).json()["enabled"] is False


# ----------------------------------------------------------------------------- limits, enforced server-side
def test_tts_text_over_limit_rejected(api):
    r = api.c.post("/api/voice/tts", json={"text": "a" * 2001}, headers=api.h())
    assert r.status_code == 422


def test_tts_empty_text_rejected(api):
    assert api.c.post("/api/voice/tts", json={"text": ""}, headers=api.h()).status_code == 422


def test_tts_rejects_unknown_fields(api):
    assert api.c.post("/api/voice/tts", json={"text": "hola", "extra": 1}, headers=api.h()).status_code == 422


def test_stt_audio_over_size_limit_rejected(api):
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = post_stt(api.c, api.h(), data=big)
    assert r.status_code == 413


def test_stt_empty_audio_rejected(api):
    assert post_stt(api.c, api.h(), data=b"").status_code == 422


def test_stt_over_duration_limit_rejected(api, monkeypatch):
    async def fake_transcribe(audio, model, device):
        return "un audio muy largo", 61.0
    monkeypatch.setattr(stt_service, "transcribe", fake_transcribe)
    assert post_stt(api.c, api.h()).status_code == 413


def test_stt_bad_audio_maps_to_422(api, monkeypatch):
    async def boom(audio, model, device):
        raise ValueError("not a real container")
    monkeypatch.setattr(stt_service, "transcribe", boom)
    assert post_stt(api.c, api.h()).status_code == 422


# ----------------------------------------------------------------------------- happy paths (fake sidecar / fake model)
def test_stt_happy_path_returns_text(api, monkeypatch):
    async def fake_transcribe(audio, model, device):
        assert audio == SMALL_AUDIO[0]
        return "hola alice", 1.2
    monkeypatch.setattr(stt_service, "transcribe", fake_transcribe)
    r = post_stt(api.c, api.h())
    assert r.status_code == 200 and r.json() == {"text": "hola alice"}


def test_tts_happy_path_returns_audio(api, net):
    net.handlers["127.0.0.1:8010"] = lambda req: httpx.Response(200, content=b"RIFFfake", headers={"content-type": "audio/wav"})
    r = api.c.post("/api/voice/tts", json={"text": "hola"}, headers=api.h())
    assert r.status_code == 200 and r.content == b"RIFFfake" and r.headers["content-type"] == "audio/wav"


def test_tts_sidecar_down_returns_503(api):
    # no handler registered for 127.0.0.1:8010 -> net fixture answers 599 -> mapped to 503
    r = api.c.post("/api/voice/tts", json={"text": "hola"}, headers=api.h())
    assert r.status_code == 503


def test_status_reports_tts_reachability(api, net):
    net.handlers["127.0.0.1:8010"] = lambda req: httpx.Response(200, json={"status": "healthy"})
    r = api.c.get("/api/voice/status", headers=api.h())
    body = r.json()
    assert body["enabled"] is True and body["tts"]["reachable"] is True
    assert body["stt"]["model"] and "loaded" in body["stt"]
