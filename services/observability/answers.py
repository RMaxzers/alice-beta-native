"""OBSERVABILITY route: resolves the sub-intent deterministically, fetches REAL data, renders a templated answer.
No LLM is involved, so no figure can be invented. Missing data is reported as missing, never as zero.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from packages.schemas.models import Privacy, Source
from services.observability.docker import DockerDenied
from services.observability.prometheus import PromError, summarize_series
from services.router.router import normalize

GiB = 1024 ** 3


def _fmt_bytes(b: float | None) -> str:
    return "sin datos" if b is None else f"{b / GiB:.1f} GiB"


def _window(text: str) -> tuple[float, str]:
    m = re.search(r"ultim[oa]s? (\d{1,3}) ?(minutos?|min|horas?|h)\b", text)
    if m:
        n = int(m.group(1))
        secs = n * 3600 if m.group(2).startswith("h") else n * 60
        return float(min(secs, 24 * 3600)), f"últimos {n} {m.group(2)}"
    if "ultima hora" in text:
        return 3600.0, "última hora"
    return 1800.0, "últimos 30 minutos"


class ObservabilityAnswerer:
    def __init__(self, state):
        self.s = state

    def _tz(self):
        return ZoneInfo(self.s.settings.alice_timezone)

    def _local(self, ts: float | str | None) -> str:
        if ts is None:
            return "—"
        dt = datetime.fromtimestamp(ts, timezone.utc) if isinstance(ts, (int, float)) else datetime.fromisoformat(ts)
        return dt.astimezone(self._tz()).strftime("%H:%M:%S")

    async def answer(self, question: str, username: str) -> tuple[str, dict, list[Source]]:
        q = normalize(question)
        src = lambda title, loc=None: Source(kind="metric", title=title, location=loc, privacy=Privacy.INTERNAL,
                                             retrieved_at=datetime.now(timezone.utc).isoformat())
        if "ultima consulta" in q:
            return await self.last_request(username)
        if re.search(r"contenedor|container|docker", q):
            return await self.containers(q)
        if "lenta" in q and ("hora" in q or "minuto" in q) or "por que alice" in q:
            return await self.why_slow(q)
        if "mas lenta" in q:
            return self.slowest()
        if re.search(r"consultas? .*(locales|cloud|nube)|cuantas consultas|cuanto gaste|cuanto costo|gasto", q):
            return self.usage_today()
        if re.search(r"modelo .*cargado|cargado en ollama|que modelo", q):
            return await self.ollama_models()
        if re.search(r"gpu|vram", q) and re.search(r"cambio|durante|ultim|evolucion|historia", q):
            return await self.gpu_history(q)
        if re.search(r"gpu|vram", q):
            return await self.gpu_now()
        if re.search(r"componente|proceso", q) and re.search(r"\bram\b|memoria", q):
            return await self.components_mem()
        if re.search(r"\bcpu\b|\bram\b|memoria", q):
            return await self.host_now()
        return await self.health()

    # ------------------------------------------------------------------ handlers
    async def health(self):
        h = await self.s.health.check_all()
        core = ["alice_api", "router", self.s.ollama.name, "qdrant", "prometheus", "grafana", "windows_exporter", "gpu"]
        problems = [k for k in core if h[k]["state"] != "healthy"]
        lines = [f"- **{k}**: {h[k]['state']} — {h[k]['detail']}" for k in core]
        opt = [f"- {k}: {h[k]['state']} — {h[k]['detail']}" for k in ("openrouter", "web", "hermes", "docker", "grafana_external")]
        head = ("Todos los componentes del núcleo respondieron a su health check."
                if not problems else f"Componentes con problemas: {', '.join(problems)}.")
        text = (f"{head}\n\n**Núcleo** (health checks reales, {self._local(time.time())}):\n" + "\n".join(lines) +
                "\n\n**Integraciones:**\n" + "\n".join(opt))
        return text, {"health": h}, [Source(kind="metric", title="Health checks de Alice", privacy=Privacy.INTERNAL,
                                           retrieved_at=datetime.now(timezone.utc).isoformat())]

    async def host_now(self):
        p = self.s.prom
        try:
            cpu, used, total, avail = [await p.instant(n) for n in
                                       ("host_cpu_percent", "host_mem_used_bytes", "host_mem_total_bytes", "host_mem_available_bytes")]
        except PromError as e:
            return f"No puedo obtener métricas del host: {e}. No muestro valores estimados.", {}, []
        v = lambda r: r["values"][0]["value"] if r["values"] else None
        age = max((r["values"][0]["age_s"] for r in (cpu, used) if r["values"]), default=None)
        text = (f"**Host Windows** (Prometheus ← windows_exporter, muestra de hace {age:.0f} s):\n"
                f"- CPU: {'sin datos' if v(cpu) is None else f'{v(cpu):.1f} % del host (todos los núcleos)'}\n"
                f"- RAM usada: {_fmt_bytes(v(used))} de {_fmt_bytes(v(total))}; disponible {_fmt_bytes(v(avail))}"
                if age is not None else "Prometheus no tiene muestras recientes de windows_exporter (sin datos, no cero).")
        return text, {"cpu": cpu, "mem_used": used, "mem_total": total}, [Source(kind="metric", title="windows_exporter vía Prometheus", location="instantáneo", privacy=Privacy.INTERNAL)]

    async def components_mem(self):
        try:
            r = await self.s.prom.instant("alice_component_mem_bytes")
        except PromError as e:
            return f"No puedo obtener la memoria por componente: {e}. No muestro valores estimados.", {}, []
        rows = sorted(((x["labels"].get("component", "?"), x["value"]) for x in r["values"]), key=lambda t: -t[1])
        if not rows:
            return ("Prometheus no tiene muestras de memoria por proceso de Alice (sin datos, no cero). "
                    "Se generan al ejecutar `Status-Alice.ps1`."), {}, []
        age = max(x["age_s"] for x in r["values"])
        top, mb = rows[0], lambda b: f"{b / 1024 ** 2:,.0f} MB".replace(",", ".")
        text = (f"**{top[0]}** es el componente que más RAM usa ahora: {mb(top[1])} (memoria privada, "
                f"Prometheus ← windows_exporter, muestra de hace {age:.0f} s).\n\n" +
                "\n".join(f"- {c}: {mb(b)}" for c, b in rows) +
                "\n\nIncluye los procesos hijos (en Ollama, los runners de cada modelo cargado). La VRAM de la GPU va aparte.")
        return text, {"components": dict(rows)}, [Source(kind="metric", title="windows_exporter + manifiestos de Alice vía Prometheus",
                                                          location="instantáneo", privacy=Privacy.INTERNAL)]

    async def gpu_now(self):
        from services.observability.samplers import sample_gpu
        import asyncio
        gpus = await asyncio.to_thread(sample_gpu)
        if not gpus:
            return "nvidia-smi no devolvió datos: no puedo informar el uso de GPU.", {}, []
        g = gpus[0]
        loaded = await self.s.ollama.running()
        lm = ", ".join(f"{x['name']} (VRAM sin datos)" if x.get("size_vram") is None else
                       f"{x['name']} ({x['size_vram'] / GiB:.1f} GiB VRAM)" for x in loaded) or "ninguno"
        text = (f"**GPU** {g['name']} (nvidia-smi, ahora):\n- VRAM: {g['used_mib']:.0f} / {g['total_mib']:.0f} MiB "
                f"({100 * g['used_mib'] / g['total_mib']:.0f} %)\n- Utilización: {g['util']:.0f} %\n"
                f"- Temperatura: {'no disponible' if g['temp_c'] is None else f'{g['temp_c']:.0f} °C'}\n"
                f"- Modelos {self.s.ollama.name} cargados: {lm}")
        return text, {"gpu": g, "ollama_loaded": loaded}, [Source(kind="metric", title="nvidia-smi + Ollama /api/ps", privacy=Privacy.INTERNAL)]

    async def gpu_history(self, q: str):
        secs, label = _window(q)
        end = time.time()
        try:
            util = await self.s.prom.range("gpu_util_percent", end - secs, end)
            mem = await self.s.prom.range("gpu_mem_used_bytes", end - secs, end)
        except PromError as e:
            return f"No puedo consultar Prometheus: {e}.", {}, []
        if util["no_data"]:
            return f"No hay series de GPU en Prometheus para {label}.", {}, []
        su, sm = summarize_series(util)[0], summarize_series(mem)[0]
        cov = util["coverage"]
        text = (f"**GPU en {label}** (Prometheus, {su['samples']} muestras, cobertura {cov['fraction'] * 100:.0f} % de la ventana, "
                f"datos desde {self._local(cov['first'])} hasta {self._local(cov['last'])}):\n"
                f"- Utilización: mín {su['min']:.0f} % · prom {su['avg']:.0f} % · máx {su['max']:.0f} % (actual {su['last']:.0f} %)\n"
                f"- VRAM usada: mín {_fmt_bytes(sm['min'])} · máx {_fmt_bytes(sm['max'])} (actual {_fmt_bytes(sm['last'])})")
        if cov["fraction"] < 0.9:
            text += f"\n- ⚠ La ventana está incompleta: solo hay datos para el {cov['fraction'] * 100:.0f} % del intervalo."
        if cov["gaps"]:
            text += f"\n- ⚠ {len(cov['gaps'])} hueco(s) sin muestras (p. ej. Alice detenida)."
        return text, {"util": su, "mem": sm, "coverage": cov}, [Source(kind="metric", title="alice_gpu_* vía Prometheus", location=label, privacy=Privacy.INTERNAL)]

    async def ollama_models(self):
        label = "LM Studio" if self.s.ollama.name == "lmstudio" else "Ollama"
        try:
            loaded = await self.s.ollama.running()
            tags = await self.s.ollama.tags()
        except Exception as e:  # noqa: BLE001
            return f"{label} no responde ({type(e).__name__}).", {}, []
        if self.s.ollama.name == "lmstudio":
            names = ", ".join(dict.fromkeys(x["name"] for x in loaded)) or "ninguno"
            text = (f"**Modelos cargados en LM Studio**: {names}.\n\n"
                    f"Disponibles: {', '.join(t['name'] for t in tags)}.\n\n"
                    "La API de LM Studio no informa la VRAM utilizada por cada modelo.")
            return text, {"loaded": loaded, "installed": [t["name"] for t in tags]}, [
                Source(kind="metric", title="LM Studio /api/v1/models", privacy=Privacy.INTERNAL)]
        lm = "\n".join(f"- {x['name']}: {x.get('size_vram', 0) / GiB:.1f} GiB en VRAM de {x.get('size', 0) / GiB:.1f} GiB "
                       f"({'100 % GPU' if x.get('size_vram') == x.get('size') else 'parcialmente en CPU'}), expira {x.get('expires_at', '')[:19]}"
                       for x in loaded) or "- Ningún modelo cargado ahora (se cargan al recibir una consulta)."
        text = f"**Modelos cargados en Ollama** (/api/ps):\n{lm}\n\nInstalados: {', '.join(t['name'] for t in tags)}"
        return text, {"loaded": loaded, "installed": [t["name"] for t in tags]}, [Source(kind="metric", title="Ollama /api/ps y /api/tags", privacy=Privacy.INTERNAL)]

    def _today_utc(self) -> str:
        local0 = datetime.now(self._tz()).replace(hour=0, minute=0, second=0, microsecond=0)
        return local0.astimezone(timezone.utc).isoformat()

    def usage_today(self):
        con = self.s.con
        rows = con.execute("SELECT provider, COUNT(*) n FROM requests WHERE started_at>=? AND status='ok' GROUP BY provider",
                           (self._today_utc(),)).fetchall()
        by = {r["provider"] or "ninguno": r["n"] for r in rows}
        local = sum(n for p, n in by.items() if p in ("ollama", "lmstudio", "local-tools", "ninguno"))
        cloud = sum(n for p, n in by.items() if p in ("openrouter", "tavily"))
        spent = self.s.ledger.spent_today()
        text = (f"**Hoy** (desde las 00:00 {self.s.settings.alice_timezone}; registro local de Alice):\n"
                f"- Consultas locales completadas: {local}\n- Consultas con salida externa (cloud/web): {cloud}\n"
                f"- Por proveedor: {by or 'sin consultas'}\n"
                f"- Coste cloud contabilizado: USD {spent['accounted']:.4f}; reservado sin conciliar: USD {spent['reserved_open']:.4f}; "
                f"llamadas con coste desconocido: {spent['unknown_cost_calls']}")
        return text, {"by_provider": by, "spent": spent}, [Source(kind="log", title="SQLite requests + ledger", privacy=Privacy.INTERNAL)]

    def slowest(self):
        r = self.s.con.execute("SELECT * FROM requests WHERE started_at>=? AND duration_s IS NOT NULL ORDER BY duration_s DESC LIMIT 1",
                               (self._today_utc(),)).fetchone()
        if not r:
            return "No hay consultas registradas hoy.", {}, []
        text = (f"**Consulta más lenta de hoy**: id `{r['request_id'][:8]}` a las {self._local(r['started_at'])}, "
                f"{r['duration_s']:.1f} s en total (cola {r['queue_s'] or 0:.1f} s, recuperación {r['retrieval_s'] or 0:.2f} s, "
                f"proveedor {r['provider_s'] or 0:.1f} s). Ruta {r['route']}, proveedor {r['provider']}, modelo {r['model']}. "
                "El contenido de la consulta no se registra.")
        return text, {"request": dict(r)}, [Source(kind="log", title="SQLite requests", privacy=Privacy.INTERNAL)]

    async def containers(self, q: str):
        if not self.s.settings.docker_enabled:
            return ("El control de contenedores desde Alice está deshabilitado en este perfil. "
                    "Consulta los servicios desde el host con docker compose ps.",
                    {"docker": {"state": "disabled"}}, [])
        d = self.s.docker
        st = d.status()
        if st["state"] != "healthy":
            return (f"No puedo consultar contenedores: {st['detail']}. Los servicios de Alice (Qdrant, Prometheus, Grafana) "
                    "corren como procesos nativos de Windows en esta beta, no como contenedores; su salud está en «¿Cómo está Alice?».",
                    {"docker": st}, [Source(kind="container", title="DockerAdapter", privacy=Privacy.INTERNAL)])
        try:
            if re.search(r"log|error", q):
                name = next((c for c in d.allowed if c.replace("alice-", "") in q), None)
                if not name:
                    return f"Indica el contenedor (permitidos: {', '.join(sorted(d.allowed))}).", {}, []
                logs = d.call("container_logs", ref=name, tail=200, since_s=3600)
                errs = [l for l in logs["lines"] if re.search(r"(?i)\b(error|err|fatal|panic)\b", l)][-20:]
                body = "\n".join(errs) if errs else "Sin líneas de error en la última hora."
                return f"**Últimos errores de {name}** (docker logs --tail 200 --since 1h):\n```\n{body}\n```", logs, []
            stats = d.call("container_stats")
            if not stats:
                return "No hay contenedores permitidos en ejecución.", {}, []
            top = sorted(stats, key=lambda s: float((s["MemPerc"] or "0").rstrip("%")), reverse=True)
            lines = "\n".join(f"- {s['Name']}: memoria {s['MemUsage']} ({s['MemPerc']}), CPU {s['CPUPerc']}" for s in top)
            return f"**Contenedores** (docker stats --no-stream, ahora):\n{lines}", {"stats": stats}, []
        except DockerDenied as e:
            return f"Operación Docker rechazada: {e}", {}, []

    async def why_slow(self, q: str):
        secs, label = _window(q)
        since = (datetime.now(timezone.utc) - timedelta(seconds=secs)).isoformat()
        rows = self.s.con.execute("SELECT * FROM requests WHERE started_at>=? AND duration_s IS NOT NULL ORDER BY duration_s DESC LIMIT 5", (since,)).fetchall()
        end = time.time()
        facts = []
        try:
            cpu = summarize_series(await self.s.prom.range("host_cpu_percent", end - secs, end))
            mem = summarize_series(await self.s.prom.range("host_mem_available_bytes", end - secs, end))
            gpu = summarize_series(await self.s.prom.range("gpu_util_percent", end - secs, end))
        except PromError as e:
            return f"No puedo consultar Prometheus: {e}.", {}, []
        if not rows:
            return f"No hay consultas registradas en {label}; no hay evidencia de lentitud que analizar.", {}, []
        for r in rows:
            parts = {"cola": r["queue_s"] or 0, "recuperación": r["retrieval_s"] or 0, "proveedor/modelo": r["provider_s"] or 0}
            dom = max(parts, key=parts.get)
            facts.append(f"- `{r['request_id'][:8]}` {self._local(r['started_at'])}: {r['duration_s']:.1f} s, mayor componente: {dom} "
                         f"({parts[dom]:.1f} s), {r['route']} / {r['model']}")
        res = []
        if cpu: res.append(f"CPU host máx {cpu[0]['max']:.0f} % (prom {cpu[0]['avg']:.0f} %)")
        if mem: res.append(f"RAM disponible mín {_fmt_bytes(mem[0]['min'])}")
        if gpu: res.append(f"GPU máx {gpu[0]['max']:.0f} %")
        text = (f"**Consultas más lentas en {label}** (registro local):\n" + "\n".join(facts) +
                f"\n\n**Recursos en la ventana** (Prometheus): {'; '.join(res) or 'sin datos'}.\n\n"
                "Interpretación: el desglose indica en qué etapa se gastó el tiempo de cada consulta. "
                "La coincidencia temporal con recursos altos es una correlación, no prueba causalidad "
                "(otros procesos del PC también consumen CPU/GPU y no se miden por proceso).")
        return text, {"requests": [dict(r) for r in rows], "cpu": cpu, "mem": mem, "gpu": gpu}, [Source(kind="metric", title="requests + Prometheus", location=label, privacy=Privacy.INTERNAL)]

    async def last_request(self, username: str):
        r = self.s.con.execute("SELECT * FROM requests WHERE finished_at IS NOT NULL AND route!='OBSERVABILITY' ORDER BY started_at DESC LIMIT 1").fetchone()
        if not r:
            return "No hay una consulta previa (no de observabilidad) registrada.", {}, []
        t0 = datetime.fromisoformat(r["started_at"]).timestamp()
        t1 = datetime.fromisoformat(r["finished_at"]).timestamp()
        base0 = t0 - 120
        end = min(time.time(), t1 + 60)
        out, data = [], {}
        for name, label, fmt in (("host_cpu_percent", "CPU host", lambda v: f"{v:.0f} %"),
                                 ("host_mem_used_bytes", "RAM usada", _fmt_bytes),
                                 ("gpu_util_percent", "GPU util", lambda v: f"{v:.0f} %"),
                                 ("gpu_mem_used_bytes", "VRAM usada", _fmt_bytes)):
            try:
                rr = await self.s.prom.range(name, base0, end, step=5)
            except PromError as e:
                return f"No puedo consultar Prometheus: {e}.", {}, []
            if rr["no_data"]:
                out.append(f"- {label}: sin datos en Prometheus para esa ventana")
                continue
            pts = rr["series"][0].points
            before = [v for t, v in pts if t < t0]
            during = [v for t, v in pts if t0 <= t <= t1 + 15]  # +1 scrape interval
            after = [v for t, v in pts if t > t1 + 15]
            if not during:
                out.append(f"- {label}: la consulta duró {t1 - t0:.1f} s, menos que el intervalo de muestreo (15 s); no hay muestra dentro de la ventana")
                continue
            b = sum(before) / len(before) if before else None
            out.append(f"- {label}: antes {'—' if b is None else fmt(b)} → durante máx {fmt(max(during))}"
                       f"{'' if not after else f' → después {fmt(after[-1])}'}")
            data[name] = {"before_avg": b, "during_max": max(during), "after_last": after[-1] if after else None}
        text = (f"**Última consulta** `{r['request_id'][:8]}`: {self._local(r['started_at'])}–{self._local(r['finished_at'])} "
                f"({r['duration_s']:.1f} s), ruta {r['route']}, proveedor **{r['provider']}**, modelo **{r['model']}**, "
                f"tokens salida {r['tokens_out'] or '—'}.\n\n**Recursos** (Prometheus, muestreo 15 s, ventana −2 min/+1 min):\n" + "\n".join(out) +
                "\n\nLos cambios coinciden en el tiempo con la consulta. "
                + ("Como el proveedor fue local (Ollama en esta GPU), es plausible que la inferencia explique el aumento de GPU/VRAM, "
                   "pero no se mide por proceso: otras cargas del PC podrían contribuir." if r["provider"] == "ollama" else
                   "El proveedor no fue local, así que los cambios de GPU/VRAM no se deben a la inferencia de esa consulta.")
                )
        return text, {"request": dict(r), "resources": data}, [Source(kind="metric", title="Prometheus + registro de consultas", location="ventana de la última consulta", privacy=Privacy.INTERNAL)]
