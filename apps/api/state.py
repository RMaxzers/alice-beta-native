"""Wires all components. One instance per process (app.state.alice)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from apps.api.config import Settings, load_yaml
from apps.api.db import connect, migrate
from apps.api.security import Sessions
from services.ingestion.pipeline import Ingestor
from services.integrations.grafana_external import GrafanaAdapter
from services.integrations.hermes import HermesAdapter
from services.integrations.web import WebSearch
from services.observability.answers import ObservabilityAnswerer
from services.observability.docker import DockerAdapter
from services.observability.health import HealthChecker
from services.observability.prometheus import PrometheusAdapter
from services.policies.egress import EgressGate
from services.providers.ledger import Ledger
from services.providers.ollama import OllamaProvider
from services.providers.lmstudio import LMStudioProvider
from services.providers.openrouter import OpenRouterProvider
from services.rag.qdrant import Qdrant
from services.router.router import Router
from services.tasks.store import TaskStore
from services.tasks.reminders import ReminderService
from services.tasks.push import PushService
from services.conversations.store import ConversationStore
from services.actions.files import FileExecutor
from services.workers.orchestrator import Orchestrator


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone
        return json.dumps({"ts": datetime.fromtimestamp(r.created, timezone.utc).isoformat(), "level": r.levelname,
                           "component": r.name, "msg": r.getMessage()}, ensure_ascii=False)


def setup_logging(settings: Settings) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(settings.logs_dir / "alice.jsonl", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    h.setFormatter(JsonFormatter())
    root = logging.getLogger("alice")
    root.setLevel(logging.INFO)
    root.handlers = [h]
    # Third-party libraries must not log request bodies/URLs with secrets.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class AliceState:
    def __init__(self, settings: Settings):
        self.settings = s = settings
        setup_logging(s)
        self.con = connect(s.ops_db)
        migrate(self.con)
        # ponytail: single-user beta — facts created before per-owner isolation belong to the configured user.
        self.con.execute("UPDATE facts SET owner=? WHERE owner IS NULL", (s.alice_username,))
        self.aliases: dict = load_yaml(s.alice_model_aliases)["aliases"]
        self.sessions = Sessions(s.alice_session_secret.get_secret_value(), self.con)
        self.local_only = s.alice_local_only
        # Existing internal callers use this attribute for the configured local provider.
        self.ollama = (LMStudioProvider(s.lmstudio_base_url, s.lmstudio_api_token.get_secret_value())
                       if s.alice_local_provider == "lmstudio" else OllamaProvider(s.ollama_base_url))
        for name, alias in self.aliases.items():
            if name.startswith("local-") and alias["provider"] != self.ollama.name:
                raise ValueError(f"El alias {name} debe usar el proveedor local {self.ollama.name}")
        self.openrouter = OpenRouterProvider(s.openrouter_api_key.get_secret_value())
        self.web = WebSearch(s.tavily_api_key.get_secret_value())
        self.hermes = HermesAdapter(s.hermes_enabled, s.hermes_api_url)
        self.docker = DockerAdapter(frozenset(x.strip() for x in s.docker_allowed_containers.split(",") if x.strip()))
        self.grafana_ext = GrafanaAdapter(s.grafana_external_enabled, s.grafana_url, s.grafana_service_account_token.get_secret_value())
        self.qdrant = Qdrant(s.qdrant_url, s.qdrant_collection)
        self.prom = PrometheusAdapter(s.prometheus_url)
        self.gate = EgressGate(self.con, cloud_enabled=s.alice_cloud_enabled, local_only=self.local_only)
        self.ledger = Ledger(self.con, s.alice_budget_per_request_usd, s.alice_budget_daily_usd, s.alice_timezone)
        emb = self.aliases["local-embedding"]
        self.embed = lambda texts: self.ollama.embed(emb["model"], texts)
        cls = self.aliases["local-classifier"]
        self.router = Router(embed=self.embed,
                             classify=lambda msgs, schema: self.ollama.complete_json(cls["model"], msgs, schema,
                                                                                     {"temperature": 0, "num_ctx": cls.get("num_ctx", 2048)}),
                             route_aliases=load_yaml(s.alice_model_aliases)["route_alias"])
        self.router_ready = False
        self.ingestor = Ingestor(self.con, s.data_dir, s.tables_db, self.qdrant, self.embed, emb["model"], emb["dimensions"],
                                 s.max_upload_mb * 1024 * 1024, s.max_pdf_pages)
        self.health = HealthChecker(self)
        self.observability = ObservabilityAnswerer(self)
        self.tasks = TaskStore(self.con, s.alice_timezone)
        self.tasks.reconcile()
        self.push = PushService(self.con, s)
        self.reminders = ReminderService(self.con, s.alice_reminders_enabled, self.push)
        self.conversations = ConversationStore(self.con)
        self.conversations.recover()
        self.file_executor = FileExecutor(self.con, s.alice_file_root, s.alice_executor_name)
        self.file_executor.recover()
        self.orchestrator = Orchestrator(self)

    def set_local_only(self, value: bool) -> None:
        self.local_only = value
        self.gate.local_only = value

    def cloud_available(self) -> bool:
        return (not self.local_only) and self.settings.alice_cloud_enabled and self.openrouter.configured

    def web_available(self) -> bool:
        return (not self.local_only) and self.settings.alice_cloud_enabled and bool(self.settings.tavily_api_key.get_secret_value())

    def recipients(self, provider: str, model: str) -> list[str]:
        if provider == "openrouter":
            return ["OpenRouter (intermediario, EE. UU.)", f"Proveedor final del modelo {model} (fallbacks deshabilitados)"]
        if provider == "tavily":
            return ["Tavily (API de búsqueda)"]
        return [provider]

    def allowed_origins(self, request) -> set[str]:
        host = request.headers.get("host", "")
        return {f"http://{host}", f"https://{host}", "http://127.0.0.1:8000", "http://localhost:8000",
                self.settings.alice_public_origin} - {""}
