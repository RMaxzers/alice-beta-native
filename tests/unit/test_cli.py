import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clients" / "cli" / "src"))
from alice_cli.main import Client, ClientError, parser
from alice_cli.storage import Storage, endpoint


def test_profiles_dpapi_and_expiry(tmp_path):
    storage = Storage(tmp_path)
    with pytest.raises(ValueError, match="sin configurar"):
        storage.url("casa")
    storage.set_url("casa", "https://private.example.test")
    def handle(r):
        if r.url.path == "/api/login":
            assert json.loads(r.content)["password"] == "test-only-secret"
            return httpx.Response(200, json={"user": "admin", "csrf": "test-csrf", "expires_at": 1},
                                  headers={"set-cookie": "alice_session=test-session; HttpOnly; Path=/"})
        assert r.headers["x-csrf-token"] == "test-csrf"
        assert "alice_session=test-session" in r.headers["cookie"]
        return httpx.Response(401, json={"detail": "expired"})
    c = Client(storage, "casa", httpx.MockTransport(handle))
    c.login("admin", "test-only-secret")
    assert "test-only-secret" not in (tmp_path / "casa.session").read_bytes().decode(errors="replace")
    assert storage.session("casa", c.url)["cookie"] == "test-session"
    with pytest.raises(ClientError) as error:
        c.request("GET", "/api/session")
    assert error.value.code == 3 and not (tmp_path / "casa.session").exists()
    c.http.close()


@pytest.mark.parametrize("url", ["http://remote.test", "https://admin:secret@remote.test", "https://remote.test/?token=x", "file:///tmp"])
def test_insecure_endpoint_rejected(url):
    with pytest.raises(ValueError):
        endpoint(url)


def test_required_commands_parse():
    for argv in (["login"], ["status"], ["chat"], ["chat", "--profile", "casa"], ["tasks", "list"]):
        assert parser().parse_args(argv).command == argv[0]


def test_stream_error_and_unknown_disconnect(tmp_path, capsys):
    storage = Storage(tmp_path)
    lines = [{"type": "conversation", "conversation_id": "abc"}, {"type": "token", "text": "hola"},
             {"type": "done", "status": "complete"}]
    def handle(r):
        return httpx.Response(200, text="\n".join(json.dumps(e) for e in lines))
    c = Client(storage, "local", httpx.MockTransport(handle))
    assert c.chat("hola") == ("abc", None, False)
    lines.pop()
    with pytest.raises(ClientError, match="podría haberse ejecutado"):
        c.chat("hola")
    c.http.close()
