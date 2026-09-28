"""services/voice/*: TTS proxy error mapping (httpx.MockTransport, no real sidecar) and STT (monkeypatched
model, no download). Route-level limits are covered in tests/security/test_voice_api.py."""
from __future__ import annotations

import httpx
import pytest

from services.voice import stt, tts


# ------------------------------------------------------------------ tts proxy
async def test_synthesize_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tts"
        assert b"hola" in request.content
        return httpx.Response(200, content=b"RIFF....WAVEfmt ", headers={"content-type": "audio/wav"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    audio, ctype = await tts.synthesize("http://127.0.0.1:8010", "hola", client=client)
    assert audio.startswith(b"RIFF") and ctype == "audio/wav"
    await client.aclose()


async def test_synthesize_passes_voice():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, content=b"x", headers={"content-type": "audio/wav"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await tts.synthesize("http://127.0.0.1:8010", "hola", voice="alba", client=client)
    await client.aclose()
    assert b"voice_url" in seen["body"] and b"alba" in seen["body"]


async def test_synthesize_sidecar_down_raises_tts_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(tts.TtsError, match="no está disponible"):
        await tts.synthesize("http://127.0.0.1:8010", "hola", client=client)
    await client.aclose()


async def test_synthesize_non_200_raises_tts_error():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    with pytest.raises(tts.TtsError, match="500"):
        await tts.synthesize("http://127.0.0.1:8010", "hola", client=client)
    await client.aclose()


async def test_check_health_true_and_false():
    ok = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert await tts.check_health("http://127.0.0.1:8010", client=ok) is True
    await ok.aclose()

    def raiser(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)
    down = httpx.AsyncClient(transport=httpx.MockTransport(raiser))
    assert await tts.check_health("http://127.0.0.1:8010", client=down) is False
    await down.aclose()


# ------------------------------------------------------------------ stt (monkeypatched model; no download)
class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeInfo:
    def __init__(self, duration):
        self.duration = duration


class FakeModel:
    def __init__(self, first_pass_text="", second_pass_text="hola desde la prueba", duration=1.5):
        self.first_pass_text = first_pass_text
        self.second_pass_text = second_pass_text
        self.duration = duration
        self.calls = []

    def transcribe(self, audio_io, language=None):
        self.calls.append(language)
        text = self.first_pass_text if language == "es" else self.second_pass_text
        return [FakeSegment(text)] if text else [], FakeInfo(self.duration)


@pytest.fixture(autouse=True)
def reset_model(monkeypatch):
    monkeypatch.setattr(stt, "_model", None)
    yield
    monkeypatch.setattr(stt, "_model", None)


async def test_transcribe_prefers_spanish_pass(monkeypatch):
    fake = FakeModel(first_pass_text="hola en español")
    monkeypatch.setattr(stt, "_model", fake)
    text, duration = await stt.transcribe(b"fake-audio-bytes", "tiny", "cpu")
    assert text == "hola en español" and duration == 1.5
    assert fake.calls == ["es"]  # second pass never needed


async def test_transcribe_falls_back_to_auto_detect(monkeypatch):
    fake = FakeModel(first_pass_text="", second_pass_text="detectado sin forzar idioma")
    monkeypatch.setattr(stt, "_model", fake)
    text, duration = await stt.transcribe(b"fake-audio-bytes", "tiny", "cpu")
    assert text == "detectado sin forzar idioma"
    assert fake.calls == ["es", None]


async def test_transcribe_both_passes_empty_returns_empty(monkeypatch):
    fake = FakeModel(first_pass_text="", second_pass_text="")
    monkeypatch.setattr(stt, "_model", fake)
    text, duration = await stt.transcribe(b"silence", "tiny", "cpu")
    assert text == "" and duration is None


def test_is_loaded_reflects_singleton(monkeypatch):
    monkeypatch.setattr(stt, "_model", None)
    assert stt.is_loaded() is False
    monkeypatch.setattr(stt, "_model", FakeModel())
    assert stt.is_loaded() is True


def test_load_reuses_existing_model_without_reconstructing(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(stt, "_model", fake)

    def boom(*a, **kw):
        raise AssertionError("should not construct a real WhisperModel when one is already loaded")
    monkeypatch.setattr(stt, "WhisperModel", boom)
    assert stt._load("tiny", "cpu") is fake
