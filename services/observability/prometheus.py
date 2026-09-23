"""Read-only Prometheus adapter with a reviewed PromQL catalog. The LLM never writes PromQL."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

MAX_RANGE_S = 24 * 3600
MAX_SERIES = 100
MAX_SAMPLES = 10_000

# name -> (promql, unit, description). Parameters are typed and substituted only from code-controlled values.
CATALOG: dict[str, tuple[str, str, str]] = {
    "host_cpu_percent": ('100 - avg(rate(windows_cpu_time_total{mode="idle"}[1m])) * 100', "% host", "CPU del host Windows (todos los núcleos)"),
    "host_mem_used_bytes": ("windows_memory_physical_total_bytes - windows_memory_available_bytes", "bytes", "RAM usada del host Windows"),
    "host_mem_total_bytes": ("windows_memory_physical_total_bytes", "bytes", "RAM total del host"),
    "host_mem_available_bytes": ("windows_memory_available_bytes", "bytes", "RAM disponible del host"),
    "host_disk_free_bytes": ('windows_logical_disk_free_bytes{volume="C:"}', "bytes", "Espacio libre en C:"),
    "host_net_bytes_per_s": ("sum(rate(windows_net_bytes_total[1m]))", "bytes/s", "Tráfico de red total"),
    "host_uptime_s": ("time() - windows_system_boot_time_timestamp", "s", "Uptime del host"),
    "gpu_util_percent": ("alice_gpu_utilization_percent", "% GPU", "Utilización GPU (nvidia-smi)"),
    "gpu_mem_used_bytes": ("alice_gpu_memory_used_bytes", "bytes", "VRAM usada"),
    "gpu_mem_total_bytes": ("alice_gpu_memory_total_bytes", "bytes", "VRAM total"),
    "gpu_temp_c": ("alice_gpu_temperature_celsius", "°C", "Temperatura GPU"),
    "gpu_power_w": ("alice_gpu_power_watts", "W", "Consumo GPU"),
    "ollama_loaded_vram_bytes": ("alice_ollama_model_loaded_vram_bytes", "bytes", "VRAM por modelo cargado en Ollama"),
    "alice_request_rate": ("sum by (route) (rate(alice_requests_total[5m]))", "req/s", "Peticiones por ruta"),
    "alice_p95_latency_s": ("histogram_quantile(0.95, sum by (le) (rate(alice_request_duration_seconds_bucket[5m])))", "s", "Latencia p95"),
    "alice_errors_rate": ("sum by (component) (rate(alice_errors_total[5m]))", "err/s", "Errores por componente"),
    "dependency_up": ("alice_dependency_up", "0/1", "Salud de dependencias"),
    "scrape_up": ("up", "0/1", "Estado de scrapes"),
}


class PromError(Exception):
    pass


@dataclass
class Series:
    labels: dict
    points: list[tuple[float, float]]


class PrometheusAdapter:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    async def _get(self, path: str, params: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{self.url}{path}", params=params)
        except httpx.HTTPError as e:
            raise PromError(f"Prometheus no disponible ({type(e).__name__})") from e
        try:
            d = r.json()
        except ValueError as e:
            raise PromError(f"Respuesta no válida de Prometheus (HTTP {r.status_code})") from e
        if d.get("status") != "success":
            raise PromError(d.get("error", "query failed"))
        return d["data"]

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                return (await c.get(f"{self.url}/-/ready")).status_code == 200
        except httpx.HTTPError:
            return False

    async def instant(self, name: str) -> dict:
        promql, unit, desc = CATALOG[name]
        data = await self._get("/api/v1/query", {"query": promql})
        res = data["result"][:MAX_SERIES]
        now = time.time()
        values = [{"labels": r["metric"], "value": float(r["value"][1]), "sample_ts": r["value"][0],
                   "age_s": round(now - r["value"][0], 1)} for r in res]
        return {"metric": name, "description": desc, "unit": unit, "query": promql, "values": values,
                "no_data": not values, "source": "prometheus", "at": datetime.now(timezone.utc).isoformat()}

    async def range(self, name: str, start: float, end: float, step: float | None = None) -> dict:
        if end <= start:
            raise PromError("Intervalo inválido")
        start = max(start, end - MAX_RANGE_S)  # clamp to 24h
        step = step or max(15.0, (end - start) / 240)
        if (end - start) / step > MAX_SAMPLES:
            step = (end - start) / MAX_SAMPLES
        promql, unit, desc = CATALOG[name]
        data = await self._get("/api/v1/query_range", {"query": promql, "start": start, "end": end, "step": step})
        series = []
        for r in data["result"][:MAX_SERIES]:
            pts = [(float(t), float(v)) for t, v in r["values"]]
            series.append(Series(r["metric"], pts))
        return {"metric": name, "description": desc, "unit": unit, "start": start, "end": end, "step": step,
                "series": series, "no_data": not series, "coverage": _coverage(series, start, end, step)}


def _coverage(series: list[Series], start: float, end: float, step: float) -> dict:
    """How much of the requested window has data, and gaps > 3 steps. Missing data is never reported as zero."""
    if not series:
        return {"fraction": 0.0, "first": None, "last": None, "gaps": []}
    ts = sorted({t for s in series for t, _ in s.points})
    expected = max(1, int((end - start) / step) + 1)
    gaps = [(a, b) for a, b in zip(ts, ts[1:]) if b - a > 3 * step]
    return {"fraction": round(min(1.0, len(ts) / expected), 3), "first": ts[0], "last": ts[-1],
            "gaps": [{"from": a, "to": b} for a, b in gaps[:10]]}


def summarize_series(r: dict) -> list[dict]:
    out = []
    for s in r["series"]:
        vals = [v for _, v in s.points]
        if not vals:
            continue
        out.append({"labels": s.labels, "min": min(vals), "max": max(vals), "avg": sum(vals) / len(vals),
                    "first": vals[0], "last": vals[-1], "samples": len(vals)})
    return out
