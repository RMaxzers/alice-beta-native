"""HermesAdapter — health-only in Beta 0.1 and DISABLED for execution (docs/DECISIONS.md D10).

Hermes exposes an OpenAI-compatible API server (gateway/platforms/api_server*.py). It is a full agent whose
profile on this machine enables terminal/code execution and cloud auxiliary models; Alice cannot impose its
egress/consent policy inside Hermes, so Alice never sends content to it. The Hermes install is not modified.
"""
from __future__ import annotations

import httpx

DISABLED_REASON = ("Deshabilitado: el perfil de Hermes incluye terminal/ejecución de código y modelos auxiliares cloud; "
                   "Alice no puede imponer su política de egress dentro de Hermes. OpenRouter directo sigue disponible.")


class HermesAdapter:
    def __init__(self, enabled: bool, api_url: str):
        self.enabled, self.api_url = enabled, api_url.rstrip("/")

    async def state(self) -> dict:
        reachable = False
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                reachable = (await c.get(f"{self.api_url}/health")).status_code == 200
        except httpx.HTTPError:
            pass
        detail = f"API server {'activo' if reachable else 'no activo'}. {DISABLED_REASON}"
        return {"state": "disabled", "detail": detail, "reachable": reachable}
