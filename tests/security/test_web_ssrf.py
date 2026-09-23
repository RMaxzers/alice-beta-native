"""§15.1 SSRF guard of the web reader. DNS is faked (no real lookups); HTTP goes to the `net` fake receiver."""
from __future__ import annotations

import ipaddress
import socket

import httpx
import pytest

from apps.api.db import connect, migrate
from packages.schemas.models import Privacy
from services.integrations import web as W
from services.integrations.web import check_url, read_url
from services.policies.egress import EgressDenied, EgressGate

FAKE_DNS = {"public.test": "93.184.216.34", "rebind.test": "10.0.0.7", "meta.test": "169.254.169.254",
            "tailnet.test": "100.100.100.100", "v6local.test": "::1"}


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *a, **k):
        if host in FAKE_DNS:
            ip = FAKE_DNS[host]
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            return [(fam, socket.SOCK_STREAM, 6, "", (ip, port))]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            raise socket.gaierror("fake DNS: unknown name (no real lookups in tests)") from None
        return real(host, port, *a, **k)  # canonical IP literals resolve locally without network
    monkeypatch.setattr(W.socket, "getaddrinfo", fake)


@pytest.fixture
def clearance(tmp_path):
    con = connect(tmp_path / "g.db")
    migrate(con)
    gate = EgressGate(con, cloud_enabled=True, local_only=False)
    return lambda url: gate.clear(username="admin", provider="web-reader", model="get", payload={"url": url}, privacy=Privacy.PUBLIC)


@pytest.mark.parametrize("url", [
    "http://localhost:8000/healthz", "http://LOCALHOST/", "http://127.0.0.1:6333/collections", "http://127.1/",
    "http://2130706433/", "http://0x7f000001/", "http://0.0.0.0:8000/", "http://[::1]:8000/", "http://[::ffff:127.0.0.1]/",
    "http://10.0.0.1/", "http://172.16.5.4/", "http://192.168.1.1/admin", "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/", "http://100.100.100.100/", "http://100.127.1.1/", "http://[fd00::1]/",
    "http://[fe80::1]/", "http://rebind.test/", "http://meta.test/", "http://tailnet.test/", "http://v6local.test/",
    "http://alice.tail1234.ts.net/", "http://printer.local/", "http://user:pass@public.test/",
    "file:///C:/Windows/win.ini", "ftp://public.test/", "gopher://public.test/", "javascript:alert(1)", "data:text/html,x",
    "http:///nohost", "//public.test/",
])
def test_blocked_destinations(url):
    with pytest.raises(EgressDenied):
        check_url(url)


def test_public_destination_allowed():
    assert check_url("https://public.test/a?b=1") == "https://public.test/a?b=1"


async def test_redirect_to_internal_is_blocked_before_connecting(net, clearance):
    net.handlers["public.test:443"] = lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1:6333/collections"})
    with pytest.raises(EgressDenied, match="privado|local"):
        await read_url("https://public.test/start", clearance("https://public.test/start"))
    assert [r.host for r in net.requests] == ["public.test:443"]


async def test_redirect_to_metadata_by_name_is_blocked(net, clearance):
    net.handlers["public.test:443"] = lambda r: httpx.Response(301, headers={"location": "http://meta.test/latest"})
    with pytest.raises(EgressDenied):
        await read_url("https://public.test/", clearance("https://public.test/"))
    assert all(r.host == "public.test:443" for r in net.requests)


async def test_redirect_loop_bounded(net, clearance):
    net.handlers["public.test:443"] = lambda r: httpx.Response(302, headers={"location": "https://public.test/again"})
    with pytest.raises(EgressDenied, match="redirecciones"):
        await read_url("https://public.test/", clearance("https://public.test/"))
    assert len(net.requests) <= 4


async def test_size_limit_and_html_stripped(net, clearance):
    body = b"<html><script>steal()</script><p>" + b"a" * (W.MAX_BYTES + 500_000) + b"</p></html>"
    net.handlers["public.test:443"] = lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=body)
    out = await read_url("https://public.test/", clearance("https://public.test/"))
    assert "steal" not in out["text"] and len(out["text"]) <= 20000


@pytest.mark.parametrize("ctype", ["application/octet-stream", "image/png", "application/x-msdownload", ""])
async def test_content_type_restricted(net, clearance, ctype):
    net.handlers["public.test:443"] = lambda r: httpx.Response(200, headers={"content-type": ctype}, content=b"MZ")
    with pytest.raises(EgressDenied, match="Tipo"):
        await read_url("https://public.test/", clearance("https://public.test/"))


async def test_total_time_limit(net, clearance, monkeypatch):
    import asyncio

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.05)
                yield b"a"

    async def slow_transport(self, request):
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=Slow(), request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", slow_transport)
    monkeypatch.setattr(W, "TIMEOUT_S", 0.3)
    with pytest.raises(EgressDenied, match="tiempo"):
        await read_url("https://public.test/", clearance("https://public.test/"))


async def test_reader_requires_clearance_for_that_exact_url(net, clearance):
    with pytest.raises(EgressDenied, match="payload_changed"):
        await read_url("https://public.test/other", clearance("https://public.test/"))
    assert net.requests == []
