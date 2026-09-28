"""services/integrations/notebooklm.py: fixed argv (never shell, never user input as a flag name), timeouts,
and status parsing — all against a fake `notebooklm` CLI (monkeypatched asyncio.create_subprocess_exec).
Must pass without the real CLI being installed or logged in."""
from __future__ import annotations

import asyncio
import json

import pytest

from services.integrations import notebooklm as N

NOTEBOOKS = [{"id": "nb123abc", "title": "Mi Notebook"}]


class FakeProc:
    def __init__(self, rc: int, out: str, err: str = ""):
        self.returncode = rc
        self._out, self._err = out.encode(), err.encode()

    async def communicate(self):
        return self._out, self._err

    def kill(self):
        pass

    async def wait(self):
        pass


def install_fake_cli(monkeypatch, calls: list, *, list_reply=None, add_reply=None, ask_reply=None,
                     auth_reply=None, rc=0):
    monkeypatch.setattr(N.shutil, "which", lambda cli: f"/usr/bin/{cli}")

    async def fake_exec(exe, *argv, **kw):
        calls.append([exe, *argv])
        if argv[0] == "list":
            return FakeProc(0, json.dumps(list_reply if list_reply is not None else NOTEBOOKS))
        if argv[0] == "source" and argv[1] == "add":
            return FakeProc(rc, json.dumps(add_reply if add_reply is not None else {"source_id": "src1"}))
        if argv[0] == "ask":
            return FakeProc(rc, json.dumps(ask_reply if ask_reply is not None else {"answer": "ok"}))
        if argv[0] == "auth" and argv[1] == "check":
            return FakeProc(1, json.dumps(auth_reply if auth_reply is not None else {
                "status": "error", "checks": {"cookies_present": False, "sid_cookie": False},
                "details": {"error": "Storage file not found"}}))
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


# ----------------------------------------------------------------------------- fixed argv / no injection
async def test_add_document_resolves_title_and_uses_fixed_argv(monkeypatch, tmp_path):
    calls: list = []
    install_fake_cli(monkeypatch, calls)
    f = tmp_path / "hoja.csv"
    f.write_text("a,b\n1,2\n")
    result = await N.add_document("Mi Notebook", f, cli="notebooklm")
    assert result == {"source_id": "src1"}
    assert calls[0] == ["/usr/bin/notebooklm", "list", "--json"]
    # the raw title never reaches the CLI as a value for -n: only the id resolved from `list`
    assert calls[1] == ["/usr/bin/notebooklm", "source", "add", str(f), "-n", "nb123abc", "--type", "file", "--json"]
    assert "Mi Notebook" not in calls[1]


async def test_ask_question_never_parsed_as_extra_flags(monkeypatch):
    calls: list = []
    install_fake_cli(monkeypatch, calls)
    tricky = "--yes --new; rm -rf /"
    result = await N.ask("nb123abc", tricky, cli="notebooklm")
    assert result == {"answer": "ok"}
    argv = calls[1]
    # the tricky text is exactly one positional argv element (the question), never split into new flags
    assert argv == ["/usr/bin/notebooklm", "ask", tricky, "-n", "nb123abc", "--json"]
    assert argv.count(tricky) == 1


async def test_unknown_notebook_ref_is_rejected(monkeypatch):
    calls: list = []
    install_fake_cli(monkeypatch, calls)
    with pytest.raises(N.NotebookLMError):
        await N.ask("no-existe", "hola", cli="notebooklm")
    # only the harmless `list` lookup ran; nothing was sent to `ask`
    assert [c[1] for c in calls] == ["list"]


# ----------------------------------------------------------------------------- timeouts
async def test_timeout_raises_notebooklm_error(monkeypatch):
    monkeypatch.setattr(N.shutil, "which", lambda cli: "/usr/bin/notebooklm")

    async def hangs(exe, *argv, **kw):
        return FakeProc(0, "{}")

    async def fake_wait_for(coro, timeout):
        coro.close() if hasattr(coro, "close") else None
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", hangs)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    with pytest.raises(N.NotebookLMError, match="Tiempo de espera"):
        await N.status(cli="notebooklm")


# ----------------------------------------------------------------------------- status parsing
async def test_status_not_installed(monkeypatch):
    monkeypatch.setattr(N.shutil, "which", lambda cli: None)
    s = await N.status(cli="notebooklm")
    assert s == {"installed": False, "logged_in": False, "detail": "CLI 'notebooklm' no encontrado en PATH"}


async def test_status_installed_not_logged_in(monkeypatch):
    calls: list = []
    install_fake_cli(monkeypatch, calls)
    s = await N.status(cli="notebooklm")
    assert s["installed"] is True and s["logged_in"] is False
    assert "Storage file not found" in s["detail"]


async def test_status_logged_in(monkeypatch):
    calls: list = []
    install_fake_cli(monkeypatch, calls, auth_reply={"status": "ok", "checks": {"cookies_present": True, "sid_cookie": True}})
    s = await N.status(cli="notebooklm")
    assert s == {"installed": True, "logged_in": True, "detail": "Sesión de Google activa"}


async def test_status_survives_non_json_output(monkeypatch):
    monkeypatch.setattr(N.shutil, "which", lambda cli: "/usr/bin/notebooklm")

    async def fake_exec(exe, *argv, **kw):
        return FakeProc(1, "not json at all")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    s = await N.status(cli="notebooklm")
    assert s["installed"] is True and s["logged_in"] is False


# ----------------------------------------------------------------------------- CLI-reported errors propagate
async def test_add_document_cli_error_raises(monkeypatch, tmp_path):
    calls: list = []
    install_fake_cli(monkeypatch, calls, add_reply={"error": True, "message": "boom"}, rc=1)
    f = tmp_path / "x.csv"
    f.write_text("a\n1\n")
    with pytest.raises(N.NotebookLMError, match="boom"):
        await N.add_document("Mi Notebook", f, cli="notebooklm")


async def test_add_document_missing_file_rejected(monkeypatch, tmp_path):
    calls: list = []
    install_fake_cli(monkeypatch, calls)
    with pytest.raises(N.NotebookLMError):
        await N.add_document("Mi Notebook", tmp_path / "no-existe.csv", cli="notebooklm")
