"""Wrapper around the unofficial `notebooklm` CLI (notebooklm-py, https://pypi.org/project/notebooklm-py/).

C2: sends document content or a question to Google. The user runs `notebooklm login` themselves in a
browser; this module never touches cookies, never automates login, and never reads the storage file.

Every CLI invocation uses a FIXED argv shape (fixed flags; only values are user data) via
`asyncio.create_subprocess_exec` (no shell). A notebook given as a title or id is always resolved
against `notebooklm list --json` first, so we only ever pass an id that is confirmed to exist to `-n`.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

NOTEBOOK_REF_RE = re.compile(r"^.{1,200}$", re.DOTALL)  # loose: validated for real by _resolve_notebook
STATUS_TIMEOUT_S = 15
CLI_TIMEOUT_S = 60
ASK_TIMEOUT_S = 120


class NotebookLMError(Exception):
    pass


async def _run(exe: str, argv: list[str], timeout: float) -> tuple[int, str, str]:
    """argv is always a fixed list of flags with data-only values; never shell=True."""
    try:
        proc = await asyncio.create_subprocess_exec(exe, *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except OSError as e:
        raise NotebookLMError(f"No se pudo ejecutar notebooklm: {e}") from e
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise NotebookLMError("Tiempo de espera agotado ejecutando notebooklm") from e
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _parse_json(out: str) -> dict | list | None:
    try:
        return json.loads(out)
    except ValueError:
        return None


def _require(cli: str) -> str:
    exe = shutil.which(cli)
    if not exe:
        raise NotebookLMError(f"CLI '{cli}' no encontrado en PATH")
    return exe


async def status(cli: str = "notebooklm") -> dict:
    """Installed? logged in? Never mutates anything: `auth check` is a local/read-only diagnostic."""
    exe = shutil.which(cli)
    if not exe:
        return {"installed": False, "logged_in": False, "detail": f"CLI '{cli}' no encontrado en PATH"}
    rc, out, err = await _run(exe, ["auth", "check", "--json"], STATUS_TIMEOUT_S)
    data = _parse_json(out)
    if not isinstance(data, dict):
        return {"installed": True, "logged_in": False, "detail": f"Respuesta inesperada del CLI: {(err or out)[:200]}"}
    if data.get("error"):
        return {"installed": True, "logged_in": False, "detail": data.get("message") or "No autenticado"}
    checks = data.get("checks") or {}
    logged_in = bool(checks.get("cookies_present")) and bool(checks.get("sid_cookie"))
    detail = "Sesión de Google activa" if logged_in else ((data.get("details") or {}).get("error") or "No autenticado: ejecuta 'notebooklm login'")
    return {"installed": True, "logged_in": logged_in, "detail": detail}


async def _resolve_notebook(cli: str, ref: str) -> str:
    """Only ever returns an id read back from `list`, never the raw client-supplied string."""
    ref = (ref or "").strip()
    if not ref or not NOTEBOOK_REF_RE.fullmatch(ref) or "\n" in ref or "\r" in ref:
        raise NotebookLMError("Identificador o título de notebook inválido")
    exe = _require(cli)
    rc, out, err = await _run(exe, ["list", "--json"], STATUS_TIMEOUT_S)
    data = _parse_json(out)
    if isinstance(data, dict) and data.get("error"):
        raise NotebookLMError(data.get("message") or "No se pudo listar los notebooks")
    if data is None:
        raise NotebookLMError(f"Respuesta inesperada del CLI: {(err or out)[:200]}")
    notebooks = data if isinstance(data, list) else (data.get("notebooks") or data.get("items") or [])
    for nb in notebooks:
        if not isinstance(nb, dict):
            continue
        nid = str(nb.get("id") or nb.get("notebook_id") or "")
        title = str(nb.get("title") or nb.get("name") or "")
        if ref == nid or ref.lower() == title.lower():
            return nid
    raise NotebookLMError(f"Notebook «{ref}» no encontrado")


def _fail_on_error(rc: int, data, err: str, out: str):
    if data is None:
        raise NotebookLMError(f"Respuesta inesperada del CLI: {(err or out)[:300]}")
    if isinstance(data, dict) and data.get("error"):
        raise NotebookLMError(data.get("message") or "El CLI devolvió error")
    if rc != 0:
        raise NotebookLMError(f"El CLI devolvió código {rc}: {(err or out)[:300]}")


async def add_document(notebook: str, file_path: Path, cli: str = "notebooklm") -> dict:
    nb_id = await _resolve_notebook(cli, notebook)
    p = Path(file_path)
    if not p.is_file():
        raise NotebookLMError("Archivo no encontrado")
    exe = _require(cli)
    argv = ["source", "add", str(p), "-n", nb_id, "--type", "file", "--json"]
    rc, out, err = await _run(exe, argv, CLI_TIMEOUT_S)
    data = _parse_json(out)
    _fail_on_error(rc, data, err, out)
    return data


async def ask(notebook: str, question: str, cli: str = "notebooklm") -> dict:
    q = (question or "").strip()
    if not q or len(q) > 4000:
        raise NotebookLMError("Pregunta vacía o demasiado larga")
    nb_id = await _resolve_notebook(cli, notebook)
    exe = _require(cli)
    argv = ["ask", q, "-n", nb_id, "--json"]
    rc, out, err = await _run(exe, argv, ASK_TIMEOUT_S)
    data = _parse_json(out)
    _fail_on_error(rc, data, err, out)
    return data
