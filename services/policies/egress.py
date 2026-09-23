"""Egress policy: the only code path that can clear content to leave the host.

External adapters (OpenRouter, Tavily, Hermes) refuse to send unless handed a Clearance whose
payload_hash matches the exact bytes they are about to send. A Clearance can only be minted here.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apps.api.db import tx
from packages.schemas.models import Privacy

TICKET_TTL = timedelta(minutes=5)


class EgressDenied(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def payload_hash(payload: dict | str) -> str:
    raw = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def effective_privacy(*levels: Privacy | str | None) -> Privacy:
    """Strictest of all inputs. Anything unlabelled counts as PRIVATE."""
    parsed = [Privacy(l) if l is not None else Privacy.PRIVATE for l in levels]
    return Privacy.strictest(*parsed) if parsed else Privacy.PRIVATE


_MINT = object()


@dataclass(frozen=True)
class Clearance:
    provider: str
    model: str
    payload_hash: str
    privacy: Privacy
    ticket_id: str | None
    _token: object = None

    def __post_init__(self):
        if self._token is not _MINT:
            raise EgressDenied("forged_clearance", "Clearance can only be created by EgressGate")

    def verify(self, provider: str, model: str, payload: dict | str) -> None:
        if (provider, model) != (self.provider, self.model):
            raise EgressDenied("destination_changed", "Provider/model differs from the authorized one")
        if payload_hash(payload) != self.payload_hash:
            raise EgressDenied("payload_changed", "Payload differs from the authorized one")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EgressGate:
    def __init__(self, con: sqlite3.Connection, *, cloud_enabled: bool, local_only: bool):
        self.con = con
        self.cloud_enabled = cloud_enabled
        self.local_only = local_only

    # --- ticket lifecycle -------------------------------------------------
    def request_ticket(self, username: str, provider: str, model: str, payload: dict | str, max_cost_usd: float) -> str:
        if self.local_only:
            raise EgressDenied("local_only", "Modo 'Solo local' activo: no se ofrecen autorizaciones de salida")
        if not self.cloud_enabled:
            raise EgressDenied("cloud_disabled", "Cloud deshabilitado en configuración")
        tid = secrets.token_urlsafe(18)
        now = _now()
        with tx(self.con):
            self.con.execute(
                "INSERT INTO egress_tickets(ticket_id, username, payload_hash, provider, model, max_cost_usd, created_at, expires_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (tid, username, payload_hash(payload), provider, model, max_cost_usd, now.isoformat(), (now + TICKET_TTL).isoformat()),
            )
        return tid

    def approve(self, ticket_id: str, username: str) -> None:
        with tx(self.con):
            row = self.con.execute("SELECT * FROM egress_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            if not row or row["username"] != username:
                raise EgressDenied("unknown_ticket", "Ticket not found for this user")
            if row["used_at"]:
                raise EgressDenied("ticket_used", "Ticket already used")
            if datetime.fromisoformat(row["expires_at"]) < _now():
                raise EgressDenied("ticket_expired", "Ticket expired")
            self.con.execute("UPDATE egress_tickets SET approved_at=? WHERE ticket_id=?", (_now().isoformat(), ticket_id))

    # --- the decision -----------------------------------------------------
    def clear(self, *, username: str, provider: str, model: str, payload: dict | str, privacy: Privacy,
              ticket_id: str | None = None, est_cost_usd: float = 0.0) -> Clearance:
        if self.local_only:
            raise EgressDenied("local_only", "Modo 'Solo local' activo: no sale contenido del equipo")
        if not self.cloud_enabled:
            raise EgressDenied("cloud_disabled", "Cloud deshabilitado en configuración")
        h = payload_hash(payload)
        if privacy == Privacy.PUBLIC and ticket_id is None:
            return Clearance(provider, model, h, privacy, None, _MINT)
        if ticket_id is None:
            raise EgressDenied("authorization_required", f"Contenido {privacy.value}: requiere autorización explícita")
        with tx(self.con):
            row = self.con.execute("SELECT * FROM egress_tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            if not row or row["username"] != username:
                raise EgressDenied("unknown_ticket", "Ticket not found for this user")
            if not row["approved_at"]:
                raise EgressDenied("not_approved", "Ticket not approved by the user")
            if row["used_at"]:
                raise EgressDenied("ticket_used", "Ticket already used (single use)")
            if datetime.fromisoformat(row["expires_at"]) < _now():
                raise EgressDenied("ticket_expired", "Ticket expired")
            if (row["provider"], row["model"]) != (provider, model):
                raise EgressDenied("destination_changed", "Provider/model differs from the authorized one")
            if row["payload_hash"] != h:
                raise EgressDenied("payload_changed", "Payload differs from the authorized one")
            if est_cost_usd > row["max_cost_usd"]:
                raise EgressDenied("cost_exceeded", "Estimated cost exceeds the authorized limit")
            self.con.execute("UPDATE egress_tickets SET used_at=? WHERE ticket_id=?", (_now().isoformat(), ticket_id))
        return Clearance(provider, model, h, privacy, ticket_id, _MINT)
