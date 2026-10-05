"""Real health checks. Nothing is reported healthy without a successful probe."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from services.observability import metrics as m
from services.observability.samplers import sample_gpu


async def _http_ok(url: str, timeout: float = 3) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url)
        return r.status_code < 400, f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        return False, type(e).__name__


class HealthChecker:
    def __init__(self, app_state):
        self.s = app_state
        self.last: dict = {}

    async def check_all(self) -> dict:
        s = self.s
        cfg = s.settings
        now = datetime.now(timezone.utc).isoformat()
        probes = {
            "qdrant": _http_ok(f"{cfg.qdrant_url}/healthz"),
            "prometheus": _http_ok(f"{cfg.prometheus_url}/-/ready"),
            "grafana": _http_ok(f"{cfg.alice_grafana_local_url}/api/health"),
            "windows_exporter": _http_ok("http://127.0.0.1:9182/health"),
        }
        results = dict(zip(probes, await asyncio.gather(*probes.values())))
        out: dict[str, dict] = {"alice_api": {"state": "healthy", "detail": "respondiendo", "checked_at": now}}
        for k, (ok, detail) in results.items():
            out[k] = {"state": "healthy" if ok else "unavailable", "detail": detail, "checked_at": now}
        local_health = await s.ollama.health()
        out[s.ollama.name] = {"state": local_health.state, "detail": local_health.detail, "checked_at": now}
        gpus = await asyncio.to_thread(sample_gpu)
        out["gpu"] = ({"state": "healthy", "detail": f"{gpus[0]['name']} VRAM {gpus[0]['used_mib']:.0f}/{gpus[0]['total_mib']:.0f} MiB", "checked_at": now}
                      if gpus else {"state": "unavailable", "detail": "nvidia-smi sin datos", "checked_at": now})
        out["router"] = {"state": "healthy" if s.router_ready else "degraded",
                         "detail": "reglas + semántico + clasificador" if s.router_ready else "solo reglas (embeddings no disponibles)",
                         "checked_at": now}
        orh = await s.openrouter.health()
        out["openrouter"] = {"state": orh.state, "detail": orh.detail, "checked_at": now}
        out["web"] = {**s.web.state(), "checked_at": now}
        out["hermes"] = {**(await s.hermes.state()), "checked_at": now}
        docker_state = (await asyncio.to_thread(s.docker.status) if cfg.docker_enabled else
                        {"state": "disabled", "detail": "Control de Docker desde Alice deshabilitado en este perfil"})
        out["docker"] = {**docker_state, "checked_at": now}
        out["grafana_external"] = {**s.grafana_ext.state(), "checked_at": now}
        for name, env in (("email", cfg.email_enabled), ("notebooklm", cfg.notebooklm_enabled), ("loki", cfg.loki_enabled)):
            out[name] = {"state": "disabled" if not env else "not_configured", "detail": "Integración opcional fuera del núcleo Beta 0.1", "checked_at": now}
        for k, v in out.items():
            if v["state"] != "disabled":
                m.DEP_UP.labels(k).set(1 if v["state"] == "healthy" else 0)
        self.last = out
        return out

    async def loop(self, interval: float = 30.0) -> None:
        while True:
            try:
                await self.check_all()
            except Exception:  # noqa: BLE001
                m.ERRORS.labels("health").inc()
            await asyncio.sleep(interval)
