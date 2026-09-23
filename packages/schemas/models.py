"""Shared contracts for Alice. Every structured decision is validated against these."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Privacy(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    PRIVATE = "PRIVATE"

    @property
    def rank(self) -> int:
        return {"PUBLIC": 0, "INTERNAL": 1, "PRIVATE": 2}[self.value]

    @staticmethod
    def strictest(*levels: "Privacy") -> "Privacy":
        return max(levels, key=lambda p: p.rank, default=Privacy.PRIVATE)


class Verification(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    EMPIRICAL = "EMPIRICAL"
    VERIFIED = "VERIFIED"


class Route(str, Enum):
    LOCAL_SIMPLE = "LOCAL_SIMPLE"
    LOCAL_CODE = "LOCAL_CODE"
    LOCAL_RAG = "LOCAL_RAG"
    CLOUD_CHEAP = "CLOUD_CHEAP"
    CLOUD_POWERFUL = "CLOUD_POWERFUL"
    WEB_RESEARCH = "WEB_RESEARCH"
    FINANCIAL_RESEARCH = "FINANCIAL_RESEARCH"
    OBSERVABILITY = "OBSERVABILITY"
    AUTOMATION = "AUTOMATION"
    STRUCTURED_QUERY = "STRUCTURED_QUERY"
    LOG_ANALYSIS = "LOG_ANALYSIS"


LOCAL_ROUTES = {Route.LOCAL_SIMPLE, Route.LOCAL_CODE, Route.LOCAL_RAG, Route.OBSERVABILITY,
                Route.AUTOMATION, Route.STRUCTURED_QUERY, Route.LOG_ANALYSIS}
EGRESS_ROUTES = {Route.CLOUD_CHEAP, Route.CLOUD_POWERFUL, Route.WEB_RESEARCH, Route.FINANCIAL_RESEARCH}


class RouteDecision(BaseModel):
    """Validated routing decision. confidence is None for rule-based decisions (not a probability)."""
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=40)
    complexity: Literal["low", "medium", "high"]
    privacy: Privacy
    requires_web: bool
    requires_rag: bool
    requires_sql: bool = False
    requires_tools: bool
    route: Route
    model_alias: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decided_by: Literal["rules", "semantic", "classifier", "policy"]
    reason: str = Field(max_length=200)


class ClassifierOutput(BaseModel):
    """What the local LLM classifier is allowed to return (then re-validated by policy)."""
    model_config = ConfigDict(extra="forbid")

    route: Route
    complexity: Literal["low", "medium", "high"]
    requires_web: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=200)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]  # the system prompt is set by the backend only
    content: str
    privacy: Privacy = Privacy.PRIVATE


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=20000)
    privacy: Privacy = Privacy.PRIVATE  # user-chosen label for THIS message only
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    force_route: Route | None = None
    authorization_ticket: str | None = None


class Source(BaseModel):
    kind: Literal["document", "table", "web", "metric", "log", "fact", "container"]
    title: str
    location: str | None = None
    url: str | None = None
    privacy: Privacy
    verification: Verification = Verification.UNVERIFIED
    retrieved_at: str | None = None


class EgressPreview(BaseModel):
    """Shown to the user before any content leaves the host."""
    provider: str
    recipients: list[str]
    model: str
    reason: str
    privacy: Privacy
    fields: list[str]
    payload_preview: str
    payload_hash: str
    estimated_cost_usd: float | None
    max_cost_usd: float | None = None  # authorized cap bound to the ticket
    ticket_request_id: str
