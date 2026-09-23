"""LOCAL_SIMPLE -> LOCAL_RAG upgrade when a specific question matches the user's own documents."""
import pytest

import services.workers.orchestrator as O
from packages.schemas.models import ChatRequest, Privacy, Route, RouteDecision


def _simple() -> RouteDecision:
    return RouteDecision(category="general", complexity="low", privacy=Privacy.PRIVATE, requires_web=False,
                         requires_rag=False, requires_tools=False, route=Route.LOCAL_SIMPLE,
                         model_alias="local-general", confidence=0.9, decided_by="classifier", reason="general")


def _orch(monkeypatch, score):
    async def fake_retrieve(con, qdrant, embed, query, owner, document_ids=None):
        return ([{"score": score}] if score is not None else []), [], 0.0
    monkeypatch.setattr(O, "retrieve", fake_retrieve)
    return O.Orchestrator(state=type("S", (), {"con": None, "qdrant": None, "embed": None})())


@pytest.mark.parametrize("msg,score,expected", [
    ("¿Qué rango está reservado para infraestructura?", 0.59, Route.LOCAL_RAG),   # specific + close match
    ("¿Qué rango está reservado para infraestructura?", 0.50, Route.LOCAL_SIMPLE),  # below threshold
    ("¿Qué rango está reservado para infraestructura?", None, Route.LOCAL_SIMPLE),  # no ready documents
    ("Explícame DHCP en pocas palabras", 0.90, Route.LOCAL_SIMPLE),                 # definitional stays general
    ("¿Qué es una VLAN?", 0.90, Route.LOCAL_SIMPLE),
])
async def test_probe_upgrade(monkeypatch, msg, score, expected):
    d = await _orch(monkeypatch, score)._maybe_rag(_simple(), ChatRequest(message=msg), "admin")
    assert d.route == expected
    if expected == Route.LOCAL_RAG:
        assert d.requires_rag and d.decided_by == "semantic" and d.privacy == Privacy.PRIVATE


async def test_probe_failure_keeps_decision(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("qdrant down")
    monkeypatch.setattr(O, "retrieve", boom)
    o = O.Orchestrator(state=type("S", (), {"con": None, "qdrant": None, "embed": None})())
    d = await o._maybe_rag(_simple(), ChatRequest(message="¿Qué rango está reservado?"), "admin")
    assert d.route == Route.LOCAL_SIMPLE
