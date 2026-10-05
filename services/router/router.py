"""Hybrid router: deterministic rules -> semantic similarity -> small local classifier -> policy validation."""
from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import ValidationError

from apps.api.config import load_yaml
from packages.schemas.models import (EGRESS_ROUTES, ClassifierOutput, Privacy, Route, RouteDecision)

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]
ClassifyFn = Callable[[list[dict], dict], Awaitable[str]]

SEMANTIC_MIN = 0.62
SEMANTIC_MARGIN = 0.04


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


@dataclass
class RouterContext:
    privacy: Privacy                      # effective privacy of the whole operation
    attached_kinds: tuple[str, ...] = ()  # kinds of attached documents
    cloud_available: bool = True          # cloud enabled, key present, not local-only
    web_available: bool = True


CLASSIFIER_PROMPT = (
    "Eres un clasificador de rutas. Responde SOLO JSON válido según el esquema. Rutas:\n"
    "LOCAL_SIMPLE: conversación, definiciones, explicaciones generales sin datos actuales.\n"
    "LOCAL_CODE: escribir o analizar código.\n"
    "LOCAL_RAG: preguntas sobre documentos del usuario.\n"
    "OBSERVABILITY: estado, métricas o recursos del sistema, GPU, contenedores, salud de Alice.\n"
    "WEB_RESEARCH: información actual o reciente de internet.\n"
    "FINANCIAL_RESEARCH: precios, mercados, datos financieros actuales.\n"
    "CLOUD_POWERFUL: tareas largas y complejas que exceden un modelo pequeño.\n"
    "CLOUD_CHEAP: tareas medianas que el usuario quiere en cloud.\n"
    "AUTOMATION: programar o automatizar tareas.\n"
    "STRUCTURED_QUERY: contar/sumar/filtrar datos tabulares.\n"
    "LOG_ANALYSIS: analizar archivos de log.\n"
    "confidence es tu estimación (0-1), no una probabilidad calibrada."
)


class Router:
    def __init__(self, embed: EmbedFn | None, classify: ClassifyFn | None, *, route_aliases: dict | None = None):
        cfg = load_yaml("config/routing/rules.yaml")
        self.rules = [
            {**r, "compiled": [re.compile(p, re.I) for p in r["patterns"]]} for r in cfg["rules"]
        ]
        self.exemplars: dict[str, list[str]] = load_yaml("config/routing/exemplars.yaml")
        self.route_alias: dict[str, str] = (route_aliases if route_aliases is not None else
                                          load_yaml("config/models/aliases.yaml")["route_alias"])
        self._embed = embed
        self._classify = classify
        self._ex_vecs: list[tuple[str, list[float]]] | None = None
        self.stats = {"malformed": 0}

    async def warmup(self) -> None:
        if self._embed is None:
            return
        pairs = [(route, text) for route, texts in self.exemplars.items() for text in texts]
        vecs = await self._embed([t for _, t in pairs])
        self._ex_vecs = [(r, v) for (r, _), v in zip(pairs, vecs)]

    # ------------------------------------------------------------------
    def _by_rules(self, text: str, ctx: RouterContext) -> RouteDecision | None:
        n = normalize(text)
        # Attachments decide first: tabular -> SQL, logs -> log analysis, others -> RAG.
        if ctx.attached_kinds:
            kinds = set(ctx.attached_kinds)
            if kinds & {"csv", "xlsx"}:
                return self._mk(Route.STRUCTURED_QUERY, "tabular", ctx, "rules", "Adjunto tabular: consulta SQL restringida", sql=True, tools=True)
            if "log" in kinds:
                return self._mk(Route.LOG_ANALYSIS, "logs", ctx, "rules", "Adjunto de log: análisis local", tools=True)
            return self._mk(Route.LOCAL_RAG, "knowledge", ctx, "rules", "Documento adjunto: RAG local", rag=True)
        for r in self.rules:
            for rx in r["compiled"]:
                if rx.search(n):
                    return self._mk(Route(r["route"]), r["category"], ctx, "rules",
                                    f"Regla determinista ({r['category']})",
                                    web=r.get("requires_web", False), rag=r.get("requires_rag", False),
                                    sql=r.get("requires_sql", False), tools=r.get("requires_tools", False))
        return None

    async def _by_semantic(self, text: str, ctx: RouterContext) -> RouteDecision | None:
        if not self._ex_vecs:
            return None
        q = (await self._embed([text]))[0]
        best: dict[str, float] = {}
        for route, v in self._ex_vecs:
            best[route] = max(best.get(route, -1.0), _cos(q, v))
        ranked = sorted(best.items(), key=lambda kv: -kv[1])
        (r1, s1), (_, s2) = ranked[0], ranked[1]
        if s1 >= SEMANTIC_MIN and s1 - s2 >= SEMANTIC_MARGIN:
            route = Route(r1)
            return self._mk(route, route.value.lower(), ctx, "semantic",
                            f"Similitud semántica con ejemplos ({s1:.2f})", confidence=round(s1, 3),
                            web=route in (Route.WEB_RESEARCH, Route.FINANCIAL_RESEARCH),
                            rag=route == Route.LOCAL_RAG, tools=route in (Route.OBSERVABILITY, Route.AUTOMATION))
        return None

    async def _by_classifier(self, text: str, ctx: RouterContext) -> RouteDecision | None:
        if self._classify is None:
            return None
        msgs = [{"role": "system", "content": CLASSIFIER_PROMPT}, {"role": "user", "content": text[:2000]}]
        raw = await self._classify(msgs, ClassifierOutput.model_json_schema())
        try:
            out = ClassifierOutput.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError):
            self.stats["malformed"] += 1
            return None
        return self._mk(out.route, out.route.value.lower(), ctx, "classifier", out.reason[:180],
                        confidence=out.confidence, complexity=out.complexity,
                        web=out.requires_web or out.route in (Route.WEB_RESEARCH, Route.FINANCIAL_RESEARCH),
                        rag=out.route == Route.LOCAL_RAG, tools=out.route in (Route.OBSERVABILITY, Route.AUTOMATION))

    def _mk(self, route: Route, category: str, ctx: RouterContext, by: str, reason: str, *, confidence=None,
            complexity=None, web=False, rag=False, sql=False, tools=False) -> RouteDecision:
        return RouteDecision(category=category, complexity=complexity or "low", privacy=ctx.privacy,
                             requires_web=web, requires_rag=rag, requires_sql=sql, requires_tools=tools,
                             route=route, model_alias=self.route_alias.get(route.value), confidence=confidence,
                             decided_by=by, reason=reason)

    def _policy(self, d: RouteDecision, ctx: RouterContext) -> RouteDecision:
        """Independent of the LLM. Never relaxes privacy; downgrades unavailable egress to local."""
        if d.route in EGRESS_ROUTES:
            needs_web = d.route in (Route.WEB_RESEARCH, Route.FINANCIAL_RESEARCH)
            unavailable = (not ctx.cloud_available) or (needs_web and not ctx.web_available)
            if unavailable:
                return d.model_copy(update={
                    "route": Route.LOCAL_SIMPLE, "model_alias": self.route_alias["LOCAL_SIMPLE"], "decided_by": "policy",
                    "requires_web": False,
                    "reason": f"{d.route.value} no disponible (cloud/web deshabilitado o sin credencial): respuesta local sin datos actuales"})
        return d

    async def route(self, text: str, ctx: RouterContext, force: Route | None = None) -> tuple[RouteDecision, float]:
        t0 = time.perf_counter()
        d: RouteDecision | None = None
        if force is not None:
            d = self._mk(force, force.value.lower(), ctx, "policy", "Ruta elegida explícitamente por el usuario",
                         web=force in (Route.WEB_RESEARCH, Route.FINANCIAL_RESEARCH))
        d = d or self._by_rules(text, ctx)
        if d is None:
            try:
                d = await self._by_semantic(text, ctx)
            except Exception:  # noqa: BLE001 — embeddings down: fall through to classifier
                d = None
        if d is None:
            try:
                d = await self._by_classifier(text, ctx)
            except Exception:  # noqa: BLE001
                d = None
        if d is None:
            d = self._mk(Route.LOCAL_SIMPLE, "general", ctx, "policy", "Sin regla ni clasificación fiable: ruta local por defecto")
        if len(text) > 1500 and d.complexity == "low":
            d = d.model_copy(update={"complexity": "medium"})
        return self._policy(d, ctx), time.perf_counter() - t0
