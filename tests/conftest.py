"""Shared test fixtures.

- `net`: a CONTROLLED FAKE RECEIVER installed at the httpx transport layer. Every HTTP request made by any
  adapter (Ollama, OpenRouter, Tavily, Prometheus, Qdrant, Hermes, web reader) is recorded and answered by
  a handler registered per host:port. Unknown destinations get 599. `net.external` lists every request that
  would have left the machine. A socket guard additionally refuses any non-loopback connect() that bypasses httpx.
- `FakeQdrant`: in-memory stand-in for the vector store (unit tests only; the real server is exercised in
  tests/integration).
- `state` / `api`: an AliceState on tmp_path (never touches the real data/ or storage/) + a logged-in TestClient.
"""
from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
FAKE_KEY = "test-key-not-real"


# ---------------------------------------------------------------------------- fake network
@dataclass
class Rec:
    method: str
    url: str
    host: str
    body: bytes

    def json(self):
        return json.loads(self.body or b"null")


def fake_vec(text: str, dim: int = 8) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    return [b / 255 for b in h[:dim]]


@dataclass
class FakeOllama:
    """Answers like Ollama on 127.0.0.1:11434. Configure .reply / .json_reply / .fail per test."""
    reply: str = "respuesta local de prueba"
    json_reply: str = '{"route":"LOCAL_SIMPLE","complexity":"low","requires_web":false,"confidence":0.9,"reason":"test"}'
    fail: bool = False
    chats: list = field(default_factory=list)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(500, text="fake ollama failure")
        p = req.url.path
        if p == "/api/version":
            return httpx.Response(200, json={"version": "fake"})
        if p in ("/api/ps", "/api/tags"):
            return httpx.Response(200, json={"models": []})
        body = json.loads(req.content or b"{}")
        if p == "/api/embed":
            return httpx.Response(200, json={"embeddings": [fake_vec(t) for t in body["input"]]})
        if p == "/api/chat":
            self.chats.append(body)
            if not body.get("stream"):
                return httpx.Response(200, json={"message": {"content": self.json_reply}})
            lines = [json.dumps({"message": {"content": self.reply}}),
                     json.dumps({"done": True, "prompt_eval_count": 10, "eval_count": 5})]
            return httpx.Response(200, content=("\n".join(lines) + "\n").encode())
        return httpx.Response(404)


def fake_openrouter(req: httpx.Request) -> httpx.Response:
    if req.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [
            {"id": m, "pricing": {"prompt": "0.000001", "completion": "0.000002"}, "context_length": 64000}
            for m in ("deepseek/deepseek-v4.1-flash", "anthropic/claude-sonnet-5")]})
    sse = ('data: {"choices":[{"delta":{"content":"respuesta cloud"}}]}\n\n'
           'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"cost":0.00001}}\n\n'
           "data: [DONE]\n\n")
    return httpx.Response(200, content=sse.encode())


def fake_tavily(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"results": [{"title": "Resultado", "url": "https://example.org/a",
                                                  "content": "contenido público", "published_date": "2026-09-01"}]})


class Net:
    def __init__(self):
        self.requests: list[Rec] = []
        self.handlers: dict[str, object] = {}
        self.ollama = FakeOllama()
        self.handlers["127.0.0.1:11434"] = self.ollama
        self.handlers["openrouter.ai:443"] = fake_openrouter
        self.handlers["api.tavily.com:443"] = fake_tavily

    @property
    def external(self) -> list[Rec]:
        return [r for r in self.requests if r.host.rsplit(":", 1)[0].strip("[]") not in LOOPBACK]

    def external_posts(self) -> list[Rec]:
        return [r for r in self.external if r.method != "GET"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        u = request.url
        key = f"{u.host}:{u.port or (443 if u.scheme == 'https' else 80)}"
        self.requests.append(Rec(request.method, str(u), key, request.content))
        h = self.handlers.get(key)
        return h(request) if h else httpx.Response(599, text="no fake receiver for " + key)


@pytest.fixture
def net(monkeypatch):
    n = Net()

    async def handle_async_request(self, request):
        await request.aread()
        resp = n.handle(request)
        return httpx.Response(resp.status_code, headers=resp.headers, content=resp.content, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async_request)
    real_connect = socket.socket.connect

    def guarded_connect(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        if host not in LOOPBACK and not str(host).startswith("127."):
            raise AssertionError(f"TEST GUARD: outbound socket connect to {addr} blocked")
        return real_connect(self, addr)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return n


# ---------------------------------------------------------------------------- fake vector store
class FakeQdrant:
    """In-memory stand-in for services.rag.qdrant.Qdrant (same async interface)."""

    def __init__(self):
        self.points: dict[str, dict] = {}
        self.fail_upsert = False

    async def health(self):
        return True

    async def ensure_collection(self, dim):
        return None

    async def upsert(self, points):
        if self.fail_upsert:
            raise RuntimeError("fake qdrant upsert failure")
        for p in points:
            self.points[p["id"]] = p

    async def search(self, vector, limit, document_ids=None):
        hits = [{"id": k, "score": 0.9, "payload": p["payload"]} for k, p in self.points.items()
                if not document_ids or p["payload"]["document_id"] in document_ids]
        return hits[:limit]

    async def delete_document(self, document_id):
        for k in [k for k, p in self.points.items() if p["payload"]["document_id"] == document_id]:
            del self.points[k]

    def for_doc(self, doc_id):
        return [p for p in self.points.values() if p["payload"]["document_id"] == doc_id]


# ---------------------------------------------------------------------------- app state / client
def make_settings(tmp_path: Path, **over):
    from apps.api.config import Settings
    base = dict(_env_file=None, data_dir=tmp_path / "data", storage_dir=tmp_path / "storage", logs_dir=tmp_path / "logs",
                alice_username="admin", alice_password="correct-horse-battery", alice_session_secret="s" * 48,
                openrouter_api_key=FAKE_KEY, tavily_api_key=FAKE_KEY, alice_cloud_enabled=True, alice_local_only=False,
                qdrant_collection="alice_unit_never_used")
    base.update(over)
    return Settings(**base)


@pytest.fixture
def make_state(tmp_path):
    from apps.api.state import AliceState

    def _mk(**over):
        st = AliceState(make_settings(tmp_path, **over))
        st.qdrant = st.ingestor.qdrant = FakeQdrant()
        return st
    return _mk


@pytest.fixture
def state(make_state, net):
    return make_state()


class Api:
    def __init__(self, client, csrf):
        self.c, self.csrf = client, csrf

    def h(self, **extra):
        return {"x-csrf-token": self.csrf, **extra}

    def chat(self, **body) -> list[dict]:
        r = self.c.post("/api/chat", json=body, headers=self.h())
        assert r.status_code == 200, r.text
        return [json.loads(l) for l in r.text.splitlines() if l.strip()]


@pytest.fixture
def client(state):
    from fastapi.testclient import TestClient
    from apps.api.main import app
    app.state.alice = state
    return TestClient(app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def api(client):
    r = client.post("/api/login", json={"username": "admin", "password": "correct-horse-battery"})
    assert r.status_code == 200, r.text
    return Api(client, r.json()["csrf"])


# ---------------------------------------------------------------------------- synthetic PDFs
def make_pdf(pages: list[str]) -> bytes:
    """Minimal valid PDF (Helvetica text, one line per page). Empty string = page without text."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 50 750 Td ({esc}) Tj ET" if text else ""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content_no = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_no} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
