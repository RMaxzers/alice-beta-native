"""Read-only adapter for an EXTERNAL Grafana (e.g. work). DISABLED by default; never mixed with local observability."""
from __future__ import annotations

import httpx

READ_PATHS = ("/api/health", "/api/search", "/api/dashboards/uid/", "/api/datasources")


class GrafanaAdapter:
    def __init__(self, enabled: bool, url: str, token: str):
        self.enabled, self.url, self._token = enabled, url.rstrip("/"), token

    def state(self) -> dict:
        if not self.enabled:
            return {"state": "disabled", "detail": "GRAFANA_EXTERNAL_ENABLED=false (por defecto)"}
        if not (self.url and self._token):
            return {"state": "not_configured", "detail": "Faltan GRAFANA_URL / GRAFANA_SERVICE_ACCOUNT_TOKEN"}
        return {"state": "configured_not_tested", "detail": self.url}

    async def get(self, path: str, params: dict | None = None) -> dict:
        if not self.enabled:
            raise PermissionError("Grafana externo deshabilitado")
        if not any(path == p or (p.endswith("/") and path.startswith(p)) for p in READ_PATHS):
            raise PermissionError("Ruta no permitida (solo lectura)")
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(self.url + path, params=params, headers={"Authorization": f"Bearer {self._token}"})
            r.raise_for_status()
            return r.json()
