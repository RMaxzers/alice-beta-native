"""REAL RAG round trip (no fakes): local Ollama (bge-m3 + qwen3) and the native Qdrant server, synthetic data only.

Isolation: tmp_path for SQLite/data, a throw-away Qdrant collection (deleted at the end), local-only + cloud disabled.
At most two local generations (GPU is shared). Skipped when Qdrant/Ollama/bge-m3 are not reachable.
"""
from __future__ import annotations

import io
import re
import uuid

import httpx
import pytest
from pypdf import PdfReader

from packages.schemas.models import ChatRequest, Privacy
from services.rag.qdrant import Qdrant
from services.rag.retrieve import retrieve
from tests.conftest import make_pdf, make_settings

pytestmark = pytest.mark.integration

QDRANT, OLLAMA = "http://127.0.0.1:6333", "http://127.0.0.1:11434"
PDF_PAGES = ["Informe del proyecto Colibri. Resumen general del trabajo realizado durante el trimestre.",
             "El servidor de pruebas del proyecto Colibri usa el puerto 8443 y se reinicia cada domingo a las 03:00.",
             "Anexo: glosario de terminos administrativos sin datos tecnicos."]
MD = ("# Guia de operacion\nEsta guia describe tareas rutinarias del equipo.\n\n"
      "## Respaldo\nLos respaldos del proyecto Colibri se guardan durante 30 dias en el disco D.\n\n"
      "## Contactos\nEl responsable de guardia rota semanalmente.\n").encode()


def _up() -> bool:
    try:
        ok = httpx.get(f"{QDRANT}/healthz", timeout=2).status_code == 200
        tags = httpx.get(f"{OLLAMA}/api/tags", timeout=2).json().get("models", [])
        return ok and any(m["name"].startswith("bge-m3") for m in tags)
    except httpx.HTTPError:
        return False


@pytest.fixture
async def st(tmp_path):
    if not _up():
        pytest.skip("Qdrant/Ollama/bge-m3 no disponibles")
    from apps.api.state import AliceState
    coll = f"alice_itest_{uuid.uuid4().hex[:8]}"
    s = AliceState(make_settings(tmp_path, qdrant_collection=coll, openrouter_api_key="", tavily_api_key="",
                                 alice_cloud_enabled=False, alice_local_only=True))
    assert s.qdrant.collection == coll and not s.cloud_available()
    yield s
    httpx.delete(f"{QDRANT}/collections/{coll}", timeout=10)
    s.con.close()


async def _ingest(st, name, data):
    row, _ = st.ingestor.register(name, data, Privacy.PRIVATE, "admin")
    await st.ingestor.process(row["document_id"])
    d = st.con.execute("SELECT * FROM documents WHERE document_id=?", (row["document_id"],)).fetchone()
    assert d["status"] == "ready", d["status_detail"]
    return d


async def _count(st, doc_id):
    r = httpx.post(f"{QDRANT}/collections/{st.qdrant.collection}/points/count", timeout=10,
                   json={"exact": True, "filter": {"must": [{"key": "document_id", "match": {"value": doc_id}}]}})
    return r.json()["result"]["count"]


async def _ask(st, q, docs):
    ev = [e async for e in st.orchestrator.chat(ChatRequest(message=q, privacy="PRIVATE", document_ids=docs), "admin")]
    assert ev[-1]["type"] == "done", ev
    text = "".join(e.get("text", "") for e in ev if e["type"] == "token")
    sources = next(e for e in ev if e["type"] == "sources")["sources"]
    return text, sources


async def test_real_rag_roundtrip(st, tmp_path):
    pdf_bytes = make_pdf(PDF_PAGES)
    pdf = await _ingest(st, "informe-colibri.pdf", pdf_bytes)
    md = await _ingest(st, "guia-operacion.md", MD)
    assert pdf["embedding_model"] == "bge-m3" and pdf["embedding_dim"] == 1024
    assert await _count(st, pdf["document_id"]) == 3 and await _count(st, md["document_id"]) == 3

    # retrieval: citations point at the real page/section
    chunks, sources, _ = await retrieve(st.con, st.qdrant, st.embed, "¿Qué puerto usa el servidor de pruebas Colibri?", "admin")
    top = chunks[0]
    assert top["document_id"] == pdf["document_id"] and top["location"] == "página 2"
    page_no = int(top["location"].split()[-1])
    assert "8443" in PdfReader(io.BytesIO(pdf_bytes)).pages[page_no - 1].extract_text()
    assert sources[0].url == f"/api/documents/{pdf['document_id']}/file"
    stored = st.settings.data_dir / pdf["stored_path"]
    assert stored.read_bytes() == pdf_bytes

    chunks, _, _ = await retrieve(st.con, st.qdrant, st.embed, "¿Cuántos días se guardan los respaldos?", "admin")
    assert chunks[0]["document_id"] == md["document_id"] and chunks[0]["location"] == "sección: Respaldo"

    # persistence: a fresh client (as after an API restart) sees the same vectors
    fresh = Qdrant(st.settings.qdrant_url, st.qdrant.collection)
    chunks2, _, _ = await retrieve(st.con, fresh, st.embed, "¿Qué puerto usa el servidor de pruebas Colibri?", "admin")
    assert chunks2[0]["location"] == "página 2"

    # generation 1: grounded answer with a resolvable citation
    text, srcs = await _ask(st, "¿Qué puerto usa el servidor de pruebas del proyecto Colibri?", [pdf["document_id"], md["document_id"]])
    assert "8443" in text
    assert any(s["title"] == "informe-colibri.pdf" and s["location"] == "página 2" for s in srcs)

    # generation 2 (at most): absent information -> honest "no evidence"
    text, _ = await _ask(st, "¿Cuál es el presupuesto anual en euros del departamento de marketing?", [pdf["document_id"], md["document_id"]])
    assert re.search(r"(?i)no (encontr|hay|contien|aparec|se (menciona|especifica|indica|incluye)|incluye|dispon|proporcion)|sin (evidencia|informaci)", text), text
    assert not re.search(r"\d[\d.,]*\s*(€|euros)", text), text

    # deletion removes vectors from the real server too
    await st.ingestor.delete(pdf["document_id"])
    assert await _count(st, pdf["document_id"]) == 0 and not stored.exists()
    assert await _count(st, md["document_id"]) == 3
