"""Periodic samplers: GPU via nvidia-smi (fixed argv, no shell) and Ollama loaded models."""
from __future__ import annotations

import asyncio
import shutil
import subprocess

import httpx

from services.observability import metrics as m

NVSMI_ARGS = ["--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
              "--format=csv,noheader,nounits"]


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None  # "[N/A]" etc. -> no sample, not zero


def sample_gpu() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        m.GPU_SAMPLE_OK.set(0)
        return []
    try:
        out = subprocess.run([exe, *NVSMI_ARGS], capture_output=True, text=True, timeout=5, shell=False, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        m.GPU_SAMPLE_OK.set(0)
        return []
    gpus = []
    for line in out.strip().splitlines():
        idx, name, util, used, total, temp, power = [x.strip() for x in line.split(",")]
        g = {"index": idx, "name": name, "util": _num(util), "used_mib": _num(used), "total_mib": _num(total),
             "temp_c": _num(temp), "power_w": _num(power)}
        gpus.append(g)
        if g["util"] is not None: m.GPU_UTIL.labels(idx).set(g["util"])
        if g["used_mib"] is not None: m.GPU_MEM_USED.labels(idx).set(g["used_mib"] * 1024 * 1024)
        if g["total_mib"] is not None: m.GPU_MEM_TOTAL.labels(idx).set(g["total_mib"] * 1024 * 1024)
        if g["temp_c"] is not None: m.GPU_TEMP.labels(idx).set(g["temp_c"])
        if g["power_w"] is not None: m.GPU_POWER.labels(idx).set(g["power_w"])
    m.GPU_SAMPLE_OK.set(1 if gpus else 0)
    return gpus


async def sample_ollama(base_url: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            tags = (await c.get(f"{base_url}/api/tags")).json().get("models", [])
            ps = (await c.get(f"{base_url}/api/ps")).json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return
    m.OLLAMA_MODELS_INSTALLED.set(len(tags))
    m.OLLAMA_MODEL_LOADED.clear()
    for x in ps:
        m.OLLAMA_MODEL_LOADED.labels(x["name"]).set(x.get("size_vram", 0))


async def run_samplers(ollama_url: str, interval: float = 15.0, *, local_provider=None) -> None:
    while True:
        await asyncio.to_thread(sample_gpu)
        if local_provider is None or local_provider.name == "ollama":
            await sample_ollama(ollama_url)
        await asyncio.sleep(interval)
