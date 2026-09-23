"""Restricted Docker broker. Only four typed read operations; everything else does not exist.

- argv lists only, shell=False; no user text is ever placed in argv except a validated container ref.
- container refs must be in the configured allowlist AND present in the live inventory.
- inspect output is projected to a fixed set of fields (no env, cmd, labels, mounts).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

ALLOWED_OPS = frozenset({"list_containers", "container_stats", "container_status", "container_logs"})
ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
LOG_DEFAULT, LOG_MAX = 200, 1000
SINCE_MAX_S = 24 * 3600
OUT_MAX = 256 * 1024
TIMEOUT_S = 5
SECRETISH = re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*\S+|bearer\s+\S+")

Runner = Callable[[list[str], int], tuple[int, str, str]]


class DockerDenied(Exception):
    pass


def _default_runner(argv: list[str], timeout: int) -> tuple[int, str, str]:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=False)
    return p.returncode, p.stdout[:OUT_MAX + 1], p.stderr[:2000]


@dataclass
class DockerAdapter:
    allowed: frozenset[str]
    runner: Runner | None = None
    exe: str | None = None

    def __post_init__(self):
        self.exe = self.exe or shutil.which("docker")
        self.runner = self.runner or _default_runner

    def status(self) -> dict:
        if not self.exe:
            return {"state": "unavailable", "detail": "Docker no instalado (decisión D1: runtime nativo, sin WSL2 en Beta 0.1)"}
        rc, _, err = self.runner([self.exe, "version", "--format", "{{.Server.Version}}"], TIMEOUT_S)
        if rc != 0:
            return {"state": "unavailable", "detail": "Daemon Docker no responde"}
        return {"state": "healthy", "detail": f"allowlist: {', '.join(sorted(self.allowed))}"}

    # --- validation ---------------------------------------------------------
    def _require(self) -> str:
        if not self.exe:
            raise DockerDenied("Docker no está instalado en este equipo (decisión D1)")
        return self.exe

    def _validate_ref(self, ref: str) -> str:
        if not isinstance(ref, str) or not ID_RE.fullmatch(ref):
            raise DockerDenied("Identificador de contenedor inválido")
        if ref not in self.allowed:
            raise DockerDenied("Contenedor fuera de la allowlist de Alice")
        live = {c["name"] for c in self._ps()}
        if ref not in live:
            raise DockerDenied("Contenedor no encontrado en el inventario actual")
        return ref

    def _run(self, argv: list[str]) -> str:
        rc, out, err = self.runner(argv, TIMEOUT_S)
        if rc != 0:
            raise DockerDenied(f"docker devolvió error: {err[:200]}")
        return out

    # --- operations -----------------------------------------------------------
    def _ps(self) -> list[dict]:
        out = self._run([self._require(), "ps", "-a", "--no-trunc", "--format", "{{json .}}"])
        rows = [json.loads(l) for l in out.splitlines() if l.strip()]
        return [{"name": r.get("Names"), "id": r.get("ID", "")[:12], "state": r.get("State"), "status": r.get("Status")}
                for r in rows]

    def list_containers(self) -> list[dict]:
        return [c for c in self._ps() if c["name"] in self.allowed]

    def container_stats(self) -> list[dict]:
        names = [c["name"] for c in self.list_containers() if c["state"] == "running"]
        if not names:
            return []
        out = self._run([self._require(), "stats", "--no-stream", "--format", "{{json .}}", *names])
        keep = ("Name", "CPUPerc", "MemUsage", "MemPerc", "NetIO", "BlockIO", "PIDs")
        return [{k: r.get(k) for k in keep} for r in (json.loads(l) for l in out.splitlines() if l.strip())]

    def container_status(self, ref: str) -> dict:
        ref = self._validate_ref(ref)
        d = json.loads(self._run([self._require(), "inspect", "--type", "container", "--", ref]))[0]
        st = d.get("State", {})
        health = (st.get("Health") or {}).get("Status")
        return {"name": d.get("Name", "").lstrip("/"), "state": st.get("Status"), "started_at": st.get("StartedAt"),
                "restart_count": d.get("RestartCount"), "oom_killed": st.get("OOMKilled"), "exit_code": st.get("ExitCode"),
                "health": health or "no instrumentada (running; sin HEALTHCHECK)"}

    def container_logs(self, ref: str, tail: int = LOG_DEFAULT, since_s: int = 3600) -> dict:
        ref = self._validate_ref(ref)
        tail = max(1, min(int(tail), LOG_MAX))
        since_s = max(1, min(int(since_s), SINCE_MAX_S))
        out = self._run([self._require(), "logs", "--tail", str(tail), "--since", f"{since_s}s", "--", ref])
        truncated = len(out) > OUT_MAX
        text = SECRETISH.sub("<REDACTED>", out[:OUT_MAX])
        return {"name": ref, "tail": tail, "since_s": since_s, "truncated": truncated, "lines": text.splitlines()}

    def call(self, op: str, **kwargs) -> object:
        """Single entry point used by the chat tool executor."""
        if op not in ALLOWED_OPS:
            raise DockerDenied(f"Operación no permitida en Beta 0.1: {op}")
        return getattr(self, op)(**kwargs)
