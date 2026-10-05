from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from apps.api.config import ROOT, load_yaml, settings
from apps.api.security import COOKIE, SESSION_TTL, external_allowed, is_proxied, require_user
from apps.api.state import AliceState
from packages.schemas.models import ChatRequest, Privacy, TaskIn, TaskPatch
from services.tasks.store import TaskError
from services.ingestion.pipeline import IngestError
from services.observability import metrics as m
from services.observability.prometheus import CATALOG, PromError, summarize_series
from services.observability.samplers import run_samplers
from services.policies.egress import EgressDenied
from services.rag.facts import FactIn, add_fact, facts_for
from services.rag.knowledge_map import document_edges

WEB_DIST = ROOT / "apps" / "web" / "dist"
# Windows' registry often lacks this type, so FileResponse would send the bundled fonts as text/plain.
mimetypes.add_type("font/woff2", ".woff2")


@asynccontextmanager
async def lifespan(app: FastAPI):
    st = AliceState(settings())
    app.state.alice = st
    m.serve(st.settings.alice_metrics_port)
    tasks = [asyncio.create_task(run_samplers(st.settings.ollama_base_url,
                                            local_provider=st.ollama)), asyncio.create_task(st.health.loop())]

    async def warm():
        while not st.router_ready:
            try:
                await st.router.warmup()
                st.router_ready = True
            except Exception:  # noqa: BLE001 — rules still work without embeddings
                st.router_ready = False
                await asyncio.sleep(15)
    tasks.append(asyncio.create_task(warm()))
    tasks.append(asyncio.create_task(st.reminders.loop()))
    tasks.append(asyncio.create_task(st.push.loop()))
    # Recover documents left mid-processing by a crash: never shown as ready.
    st.con.execute("UPDATE documents SET status='failed', status_detail='interrumpido; reintentar' WHERE status IN ('pending','processing')")
    yield
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Alice", version="0.1.0-beta.1", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# Feature routers (each module owns its /api/<area> routes and tests).
from apps.api import routes_agenda, routes_conversations, routes_knowledge_extra, routes_memory, routes_voice  # noqa: E402
for _r in (routes_agenda.router, routes_conversations.router, routes_memory.router, routes_voice.router, routes_knowledge_extra.router):
    app.include_router(_r)


@app.middleware("http")
async def guard(request: Request, call_next):
    if is_proxied(request) and not external_allowed(request.url.path):
        return JSONResponse({"detail": "No encontrado"}, status_code=404)
    resp: Response = await call_next(request)
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def S(request: Request) -> AliceState:
    return request.app.state.alice


# ------------------------------------------------------------------ internal (loopback only)
@app.get("/healthz")
async def healthz(request: Request):
    if is_proxied(request):
        raise HTTPException(404)
    st = S(request)
    h = st.health.last or await st.health.check_all()
    return {"ok": True, "router_ready": st.router_ready,
            "integrations": {k: {"state": h[k]["state"], "detail": h[k]["detail"]} for k in ("hermes", "openrouter", "web", "docker")}}


# ------------------------------------------------------------------ auth
class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


@app.post("/api/login")
async def login(body: Login, request: Request):
    st = S(request)
    key = request.headers.get("x-forwarded-for", request.client.host if request.client else "?")
    # X-Forwarded-For is client-controlled locally; the per-username bucket can't be dodged by rotating it.
    user_key = "user:" + body.username
    st.sessions.throttle(key)
    st.sessions.throttle(user_key)
    ok_user = hmac.compare_digest(body.username, st.settings.alice_username)
    ok_pw = hmac.compare_digest(body.password.encode(), st.settings.alice_password.get_secret_value().encode())
    if not (ok_user and ok_pw):
        st.sessions.fail(key)
        st.sessions.fail(user_key)
        await asyncio.sleep(0.5)
        raise HTTPException(401, "Credenciales inválidas")
    token, csrf = st.sessions.issue(body.username)
    resp = JSONResponse({"user": body.username, "csrf": csrf, "expires_at": int(time.time()) + SESSION_TTL})
    secure = request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
    resp.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="strict", secure=secure, path="/")
    return resp


@app.post("/api/logout")
async def logout(request: Request, user: str = Depends(require_user)):
    S(request).sessions.revoke(request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/session")
async def session(request: Request):
    s = S(request).sessions.read(request.cookies.get(COOKIE))
    if not s:
        raise HTTPException(401, "No autenticado")
    return {"user": s["u"], "csrf": s["csrf"], "expires_at": s["exp"]}


# ------------------------------------------------------------------ chat
@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request, user: str = Depends(require_user)):
    return await routes_conversations.persistent_chat(req, request, user)


@app.post("/api/egress/{ticket_id}/approve")
async def approve(ticket_id: str, request: Request, user: str = Depends(require_user)):
    try:
        S(request).gate.approve(ticket_id, user)
    except EgressDenied as e:
        raise HTTPException(409, e.detail) from e
    return {"ok": True, "ticket": ticket_id}


# ------------------------------------------------------------------ knowledge
def _doc_out(r) -> dict:
    d = dict(r)
    d.pop("stored_path", None)
    return d


@app.get("/api/documents")
async def documents(request: Request, user: str = Depends(require_user)):
    rows = S(request).con.execute("SELECT * FROM documents WHERE owner=? ORDER BY ingested_at DESC", (user,)).fetchall()
    return [_doc_out(r) for r in rows]


@app.post("/api/documents")
async def upload(request: Request, file: UploadFile = File(...), privacy: Privacy = Form(Privacy.PRIVATE),
                 user: str = Depends(require_user)):
    st = S(request)
    limit = st.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    try:
        row, new = st.ingestor.register(file.filename or "archivo", data, privacy, user)
    except IngestError as e:
        raise HTTPException(422, str(e)) from e
    if new:
        st.ingestor.start(row["document_id"])
    return {"document": {k: v for k, v in row.items() if k != "stored_path"}, "duplicate": not new}


@app.get("/api/documents/{doc_id}")
async def document(doc_id: str, request: Request, user: str = Depends(require_user)):
    r = S(request).con.execute("SELECT * FROM documents WHERE document_id=? AND owner=?", (doc_id, user)).fetchone()
    if not r:
        raise HTTPException(404)
    return _doc_out(r)


@app.get("/api/documents/{doc_id}/file")
async def document_file(doc_id: str, request: Request, user: str = Depends(require_user)):
    st = S(request)
    r = st.con.execute("SELECT * FROM documents WHERE document_id=? AND owner=?", (doc_id, user)).fetchone()
    if not r:
        raise HTTPException(404)
    base = (st.settings.data_dir / "raw").resolve()
    p = (st.settings.data_dir / r["stored_path"]).resolve()
    if base not in p.parents:
        raise HTTPException(404)
    media = "application/pdf" if r["kind"] == "pdf" else "text/plain; charset=utf-8"
    return FileResponse(p, media_type=media, filename=r["original_name"],
                        content_disposition_type="inline" if r["kind"] == "pdf" else "attachment")


@app.post("/api/documents/{doc_id}/cancel")
async def cancel_doc(doc_id: str, request: Request, user: str = Depends(require_user)):
    st = S(request)
    if not st.con.execute("SELECT 1 FROM documents WHERE document_id=? AND owner=?", (doc_id, user)).fetchone():
        raise HTTPException(404)
    return {"cancelled": st.ingestor.cancel(doc_id)}


@app.delete("/api/documents/{doc_id}")
async def delete_doc(doc_id: str, request: Request, user: str = Depends(require_user)):
    st = S(request)
    if not st.con.execute("SELECT 1 FROM documents WHERE document_id=? AND owner=?", (doc_id, user)).fetchone():
        raise HTTPException(404)
    await st.ingestor.delete(doc_id)
    return {"deleted": doc_id}


@app.get("/api/knowledge/map")
async def knowledge_map(request: Request, user: str = Depends(require_user)):
    """Ready documents of this user as nodes, connected by semantic similarity of their chunk centroids."""
    st = S(request)
    rows = st.con.execute("SELECT document_id, original_name, kind, privacy, chunks FROM documents "
                          "WHERE owner=? AND status='ready' ORDER BY ingested_at", (user,)).fetchall()
    nodes = [{"id": r["document_id"], "name": r["original_name"], "kind": r["kind"], "privacy": r["privacy"],
              "chunks": r["chunks"] or 0} for r in rows]
    if len(nodes) < 2:
        return {"nodes": nodes, "edges": []}
    vectors = await st.qdrant.vectors_by_document([n["id"] for n in nodes])
    return {"nodes": nodes, "edges": document_edges(vectors)}


@app.get("/api/datasets")
async def datasets(request: Request, user: str = Depends(require_user)):
    return [dict(r) for r in S(request).con.execute("SELECT * FROM datasets WHERE owner=?", (user,))]


# ------------------------------------------------------------------ facts
@app.post("/api/facts")
async def create_fact(f: FactIn, request: Request, user: str = Depends(require_user)):
    try:
        return add_fact(S(request).con, f, user)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/facts")
async def list_facts(request: Request, subject: str | None = None, user: str = Depends(require_user)):
    con = S(request).con
    if subject:
        return facts_for(con, subject, user)
    return {"facts": [dict(r) for r in con.execute("SELECT * FROM facts WHERE owner=? ORDER BY created_at DESC LIMIT 200", (user,))],
            "conflict": []}


# ------------------------------------------------------------------ tasks (C0 reads, C1 local changes)
def _tasks(fn):
    try:
        return fn()
    except TaskError as e:
        raise HTTPException(e.status, e.detail) from e


class ReorderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=200)


@app.get("/api/today")
async def today(request: Request, user: str = Depends(require_user)):
    return S(request).tasks.today(user)


@app.get("/api/reminders")
async def reminders(request: Request, limit: int = 20, user: str = Depends(require_user)):
    return S(request).reminders.list(user, limit)


@app.post("/api/reminders/{reminder_id}/ack")
async def acknowledge_reminder(reminder_id: int, request: Request, user: str = Depends(require_user)):
    return _tasks(lambda: S(request).reminders.acknowledge(user, reminder_id))


@app.get("/api/tasks")
async def list_tasks(request: Request, status: str = "draft,open,in_progress", limit: int = 50, offset: int = 0,
                     user: str = Depends(require_user)):
    statuses = [s for s in status.split(",") if s in ("draft", "open", "in_progress", "done", "cancelled")]
    if not statuses:
        raise HTTPException(422, "Estado no válido")
    return S(request).tasks.list(user, statuses, max(1, min(limit, 200)), max(0, offset))


@app.post("/api/tasks", status_code=201)
async def create_task(body: TaskIn, request: Request, user: str = Depends(require_user)):
    key = request.headers.get("idempotency-key")
    if key is not None and not (8 <= len(key) <= 100):
        raise HTTPException(422, "Idempotency-Key inválida")
    # An explicit UI click is the user's own instruction (C1). Sources only mark where the task came from.
    return _tasks(lambda: S(request).tasks.create(user, body, origin="evidence" if body.sources else "user", actor=user, idem_key=key))


@app.patch("/api/tasks/{task_id}")
async def patch_task(task_id: str, body: TaskPatch, request: Request, user: str = Depends(require_user)):
    return _tasks(lambda: S(request).tasks.update(user, task_id, body, origin="user", actor=user))


@app.post("/api/tasks/reorder")
async def reorder_tasks(body: ReorderIn, request: Request, user: str = Depends(require_user)):
    return _tasks(lambda: S(request).tasks.reorder(user, body.ids, origin="user", actor=user))


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, user: str = Depends(require_user)):
    return _tasks(lambda: S(request).tasks.events(user, task_id))


@app.post("/api/events/{event_id}/undo")
async def undo_event(event_id: int, request: Request, user: str = Depends(require_user)):
    return _tasks(lambda: S(request).tasks.undo(user, event_id, actor=user))


@app.get("/api/actions")
async def list_actions(request: Request, limit: int = 20, user: str = Depends(require_user)):
    return S(request).tasks.actions(user, max(1, min(limit, 100)))


# ------------------------------------------------------------------ observability / models / system
@app.get("/api/observability/overview")
async def overview(request: Request, user: str = Depends(require_user)):
    st = S(request)
    h = st.health.last or await st.health.check_all()
    out = {"health": h, "metrics": {}}
    for name in ("host_cpu_percent", "host_mem_used_bytes", "host_mem_total_bytes", "gpu_util_percent",
                 "gpu_mem_used_bytes", "gpu_mem_total_bytes", "gpu_temp_c"):
        try:
            r = await st.prom.instant(name)
            out["metrics"][name] = {"value": r["values"][0]["value"] if r["values"] else None, "unit": r["unit"],
                                    "age_s": r["values"][0]["age_s"] if r["values"] else None}
        except PromError as e:
            out["metrics"][name] = {"value": None, "error": str(e)}
    out["usage_today"] = st.observability.usage_today()[1]
    out["recent_requests"] = [dict(r) for r in st.con.execute(
        "SELECT request_id, started_at, route, provider, model, status, duration_s FROM requests ORDER BY started_at DESC LIMIT 15")]
    for r in out["recent_requests"]:
        r["request_id"] = r["request_id"][:8]
    out["grafana_url"] = st.settings.alice_grafana_local_url.rstrip("/") + "/d/alice-overview"
    return out


@app.get("/api/observability/range")
async def obs_range(metric: str, minutes: int = 30, request: Request = None, user: str = Depends(require_user)):
    if metric not in CATALOG:
        raise HTTPException(422, "Métrica no incluida en el catálogo")
    minutes = max(1, min(minutes, 24 * 60))
    end = time.time()
    try:
        r = await S(request).prom.range(metric, end - minutes * 60, end)
    except PromError as e:
        raise HTTPException(503, str(e)) from e
    return {"metric": metric, "unit": r["unit"], "description": r["description"], "coverage": r["coverage"],
            "series": [{"labels": s.labels, "points": s.points} for s in r["series"]], "summary": summarize_series(r)}


@app.get("/api/observability/catalog")
async def obs_catalog(user: str = Depends(require_user)):
    return [{"name": k, "unit": unit, "description": desc} for k, (_, unit, desc) in CATALOG.items()]


@app.get("/api/models")
async def models(request: Request, user: str = Depends(require_user)):
    st = S(request)
    try:
        loaded = {x["name"]: x for x in await st.ollama.running()}
        installed = {x["name"]: x for x in await st.ollama.tags()}
        ollama_ok = True
    except Exception:  # noqa: BLE001
        loaded, installed, ollama_ok = {}, {}, False
    out = []
    for alias, a in st.aliases.items():
        row = {"alias": alias, "provider": a["provider"], "model": a["model"]}
        if a["provider"] in ("ollama", "lmstudio"):
            full = (a["model"] if a["provider"] != "ollama" or ":" in a["model"] else a["model"] + ":latest")
            row.update(available=full in installed, loaded=full in loaded,
                       vram_bytes=loaded.get(full, {}).get("size_vram"), size_bytes=installed.get(full, {}).get("size"),
                       location="local (LM Studio / enlace SSH)" if a["provider"] == "lmstudio" else "local (este PC)")
        else:
            h = await st.openrouter.health()
            row.update(available=st.cloud_available(), state=h.state, detail=h.detail, location="cloud (OpenRouter)",
                       pricing=await _safe_pricing(st, a["model"]) if st.cloud_available() else None)
        out.append(row)
    route_alias = load_yaml(st.settings.alice_model_aliases)["route_alias"]
    return {"ollama_reachable": ollama_ok, "local_reachable": ollama_ok,
            "local_provider": st.ollama.name, "aliases": out, "routes": route_alias,
            "future_providers": {k: ("READY_FOR_CONFIGURATION" if getattr(st.settings, f"{k}_api_key").get_secret_value() else "DISABLED")
                                 for k in ("deepseek", "anthropic", "openai", "gemini")}}


async def _safe_pricing(st, model):
    try:
        p = await st.openrouter.pricing(model)
        return None if p is None else {"usd_per_mtok_in": p["prompt"] * 1e6, "usd_per_mtok_out": p["completion"] * 1e6}
    except Exception:  # noqa: BLE001
        return None


@app.get("/api/system")
async def system(request: Request, user: str = Depends(require_user)):
    st = S(request)
    return {"health": await st.health.check_all(), "local_only": st.local_only,
            "budget": {"per_request_usd": st.settings.alice_budget_per_request_usd, "daily_usd": st.settings.alice_budget_daily_usd,
                       "today": st.ledger.spent_today()},
            "remote": {"public_origin": st.settings.alice_public_origin or None, "via_proxy": is_proxied(request)},
            "grafana_local": st.settings.alice_grafana_local_url, "version": app.version}


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_only: bool


@app.put("/api/settings")
async def put_settings(body: SettingsPatch, request: Request, user: str = Depends(require_user)):
    S(request).set_local_only(body.local_only)
    return {"local_only": body.local_only}


@app.get("/api/settings")
async def get_settings(request: Request, user: str = Depends(require_user)):
    st = S(request)
    cfg = st.settings
    configured = lambda v: "configurada" if v.get_secret_value() else "no configurada"
    voice = await routes_voice.voice_status(request, user)
    return {"local_only": st.local_only, "cloud_enabled": cfg.alice_cloud_enabled,
            "voice": {"enabled": voice["enabled"], "stt": voice["enabled"] and voice["stt"]["loaded"],
                      "tts": voice["enabled"] and voice["tts"]["reachable"]},
            "budget_per_request_usd": cfg.alice_budget_per_request_usd, "budget_daily_usd": cfg.alice_budget_daily_usd,
            "timezone": cfg.alice_timezone, "max_upload_mb": cfg.max_upload_mb,
            "credentials": {"OPENROUTER_API_KEY": configured(cfg.openrouter_api_key), "TAVILY_API_KEY": configured(cfg.tavily_api_key),
                            "DEEPSEEK_API_KEY": configured(cfg.deepseek_api_key), "GRAFANA_SERVICE_ACCOUNT_TOKEN": configured(cfg.grafana_service_account_token)},
            "features": {"hermes": cfg.hermes_enabled, "grafana_external": cfg.grafana_external_enabled, "email": cfg.email_enabled,
                         "notebooklm": cfg.notebooklm_enabled, "loki": cfg.loki_enabled, "docker": cfg.docker_enabled}}


# ------------------------------------------------------------------ static UI (SPA)
@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    if WEB_DIST.exists():
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and WEB_DIST.resolve() in f.parents:
            # Vite puts a content hash in every file under assets/, so those never go stale.
            immutable = path.startswith("assets/")
            media = "text/javascript" if path == "sw.js" else "application/manifest+json" if path == "manifest.webmanifest" else None
            return FileResponse(f, media_type=media, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        if path in ("sw.js", "manifest.webmanifest"):
            raise HTTPException(404, "Recurso web no compilado")
        # index.html names the current hashed bundles: always revalidate, or a rebuild stays invisible.
        return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "UI no compilada: ejecuta Setup-Alice.ps1"}, status_code=503)
