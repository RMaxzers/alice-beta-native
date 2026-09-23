"""Session auth (HMAC-signed cookie), CSRF double-submit, login throttling, external-path allowlist."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from apps.api.db import tx

COOKIE = "alice_session"
SESSION_TTL = 12 * 3600

# Paths reachable through Tailscale Serve (requests carrying X-Forwarded-For). Everything else is loopback-only.
EXTERNAL_PREFIXES = ("/api/", "/assets/")
EXTERNAL_EXACT = ("/", "/index.html", "/favicon.svg")
EXTERNAL_DENY = ("/api/internal/",)


def is_proxied(request: Request) -> bool:
    return "x-forwarded-for" in request.headers or "tailscale-user-login" in request.headers


def external_allowed(path: str) -> bool:
    if any(path.startswith(p) for p in EXTERNAL_DENY):
        return False
    return path in EXTERNAL_EXACT or any(path.startswith(p) for p in EXTERNAL_PREFIXES)


class Sessions:
    """Signed cookie + server-side session row (sid) so logout really ends the session."""

    def __init__(self, secret: str, con: sqlite3.Connection):
        if len(secret) < 32:
            raise RuntimeError("ALICE_SESSION_SECRET ausente o corto: ejecuta Setup-Alice.ps1")
        self.key = secret.encode()
        self.con = con
        self.failures: dict[str, deque] = defaultdict(deque)

    def _sign(self, body: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.key, body, hashlib.sha256).digest()).decode().rstrip("=")

    def issue(self, username: str) -> tuple[str, str]:
        csrf, sid, now = secrets.token_urlsafe(24), secrets.token_urlsafe(18), int(time.time())
        with tx(self.con):
            self.con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            self.con.execute("INSERT INTO sessions VALUES (?,?,?,?)", (sid, username, str(now), now + SESSION_TTL))
        body = base64.urlsafe_b64encode(json.dumps({"u": username, "exp": now + SESSION_TTL, "csrf": csrf, "sid": sid}).encode())
        return body.decode() + "." + self._sign(body), csrf

    def revoke(self, token: str | None) -> None:
        data = self.read(token)
        if data:
            with tx(self.con):
                self.con.execute("DELETE FROM sessions WHERE sid=?", (data["sid"],))

    def read(self, token: str | None) -> dict | None:
        if not token or "." not in token:
            return None
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(body.encode())):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(body.encode()))
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("exp", 0) <= time.time() or not data.get("sid"):
            return None
        row = self.con.execute("SELECT username FROM sessions WHERE sid=?", (data["sid"],)).fetchone()
        return data if row and row["username"] == data.get("u") else None

    def throttle(self, key: str) -> None:
        q = self.failures[key]
        now = time.time()
        while q and now - q[0] > 300:
            q.popleft()
        if len(q) >= 5:
            raise HTTPException(429, "Demasiados intentos; espera unos minutos")

    def fail(self, key: str) -> None:
        self.failures[key].append(time.time())


def require_user(request: Request) -> str:
    s = request.app.state.alice.sessions.read(request.cookies.get(COOKIE))
    if not s:
        raise HTTPException(401, "No autenticado")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        tok = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(tok, s["csrf"]):
            raise HTTPException(403, "CSRF inválido")
        origin = request.headers.get("origin")
        if origin and origin not in request.app.state.alice.allowed_origins(request):
            raise HTTPException(403, "Origen no permitido")
    return s["u"]
