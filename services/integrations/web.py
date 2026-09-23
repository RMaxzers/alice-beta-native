"""Web research: Tavily search (egress-gated) + SSRF-safe URL reader."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from services.policies.egress import Clearance, EgressDenied

TAVILY = "https://api.tavily.com/search"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT_S = 20.0  # total wall time for one read, including redirects and slow bodies
ALLOWED_TYPES = ("text/html", "text/plain", "application/json", "application/xhtml+xml")


def search_payload(query: str, topic: str) -> dict:
    return {"query": query, "topic": topic, "max_results": 6, "search_depth": "basic", "include_answer": False}


class WebSearch:
    name = "tavily"

    def __init__(self, api_key: str):
        self._key = api_key
        self.last: dict | None = None

    def state(self) -> dict:
        if not self._key:
            return {"state": "not_configured", "detail": "TAVILY_API_KEY ausente: investigación web no configurada"}
        return self.last or {"state": "configured_not_tested", "detail": "Tavily configurado; sin búsqueda real todavía"}

    async def search(self, query: str, topic: str, clearance: Clearance) -> list[dict]:
        payload = search_payload(query, topic)
        clearance.verify(self.name, "search", payload)
        if not self._key:
            raise EgressDenied("not_configured", "Investigación web no configurada")
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(TAVILY, json=payload, headers={"Authorization": f"Bearer {self._key}"})
        if r.status_code != 200:
            self.last = {"state": "degraded", "detail": f"HTTP {r.status_code}"}
            raise EgressDenied("search_failed", f"Tavily HTTP {r.status_code}")
        self.last = {"state": "healthy", "detail": "última búsqueda OK"}
        fetched = datetime.now(timezone.utc).isoformat()
        return [{"title": x.get("title"), "url": x.get("url"), "content": (x.get("content") or "")[:1200],
                 "published_date": x.get("published_date"), "retrieved_at": fetched} for x in r.json().get("results", [])]


# ---------------------------------------------------------------- SSRF-safe reader
def _ip_blocked(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    # not is_global also covers 100.64.0.0/10 (CGNAT / Tailscale tailnet), benchmark and documentation ranges.
    return (not a.is_global or a.is_multicast
            or (a.version == 6 and a.ipv4_mapped is not None and _ip_blocked(str(a.ipv4_mapped))))


def check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise EgressDenied("ssrf", "Esquema no permitido")
    if not u.hostname or u.username or u.password:
        raise EgressDenied("ssrf", "URL inválida")
    host = u.hostname.lower()
    if host in ("localhost", "metadata.google.internal") or host.endswith((".local", ".internal", ".ts.net")):
        raise EgressDenied("ssrf", "Destino interno bloqueado")
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise EgressDenied("ssrf", "No se pudo resolver el host") from e
    for info in infos:
        if _ip_blocked(info[4][0]):
            raise EgressDenied("ssrf", "Destino privado/local bloqueado")
    return url


async def read_url(url: str, clearance: Clearance) -> dict:
    """Reads a public URL. Every redirect hop is re-validated. Size/time/type bounded."""
    clearance.verify("web-reader", "get", {"url": url})
    try:
        async with asyncio.timeout(TIMEOUT_S):
            return await _read(url)
    except TimeoutError as e:
        raise EgressDenied("timeout", f"Lectura excedió el tiempo máximo ({TIMEOUT_S:.0f} s)") from e


async def _read(url: str) -> dict:
    # ponytail: DNS is re-resolved by httpx after check_url (TOCTOU/DNS-rebinding window); pin IPs via a custom transport if needed.
    for _ in range(4):
        check_url(url)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            async with c.stream("GET", url, headers={"User-Agent": "AliceBeta/0.1"}) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                ctype = r.headers.get("content-type", "").split(";")[0].strip()
                if ctype not in ALLOWED_TYPES:
                    raise EgressDenied("content_type", f"Tipo no permitido: {ctype}")
                buf = b""
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        break
                text = buf[:MAX_BYTES].decode(errors="replace")
                if ctype != "text/plain":
                    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
                    text = re.sub(r"<[^>]+>", " ", text)
                return {"url": url, "status": r.status_code, "text": re.sub(r"\s+", " ", text)[:20000],
                        "retrieved_at": datetime.now(timezone.utc).isoformat()}
    raise EgressDenied("ssrf", "Demasiadas redirecciones")
