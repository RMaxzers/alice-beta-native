"""Autonomy policy: the server decides what Alice may do on its own. Deterministic and independent of the LLM.

Levels (docs/AUTONOMY.md):
  C0 read            -> run, cite evidence
  C1 local reversible -> run when the USER's own instruction (or a UI click) defines the scope; log + undo
  C2 external/hard to reverse -> needs a specific, bound, unexpired authorization; no C2 executor exists yet
  C3 high impact     -> never automated; human review at the point of impact

The model may *propose* a level; it can only raise the server's level, never lower it.
Text from documents, logs or the web is data: an instruction found there never grants C1+ execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Level(str, Enum):
    C0 = "C0"
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"


# Every tool Alice can execute, with its fixed level. Anything not listed is C3.
TOOL_LEVEL: dict[str, Level] = {
    "task.list": Level.C0,
    "task.plan_day": Level.C0,
    "task.create": Level.C1,
    "task.update": Level.C1,
    "task.reorder": Level.C1,
    "task.undo": Level.C1,
    "memory.recall": Level.C0,
    "memory.retain": Level.C1,        # local, reversible (delete)
    "memory.forget": Level.C1,
    "notebooklm.add_source": Level.C2,  # document content leaves the machine (Google)
    "notebooklm.ask": Level.C2,
}

# Instruction provenance. Only "user" (typed in this request) and "ui" (explicit click) can authorize C1.
Origin = Literal["user", "ui", "evidence", "model"]
Verdict = Literal["execute", "propose", "awaiting_authorization", "needs_review"]


@dataclass(frozen=True)
class Decision:
    level: Level
    verdict: Verdict
    reason: str


def level_for(tool: str, proposed: Level | None = None) -> Level:
    base = TOOL_LEVEL.get(tool, Level.C3)
    if proposed is not None and int(proposed.value[1]) > int(base.value[1]):
        return proposed
    return base


def decide(tool: str, origin: Origin, *, proposed: Level | None = None, ambiguous: bool = False) -> Decision:
    lvl = level_for(tool, proposed)
    if lvl == Level.C0:
        return Decision(lvl, "execute", "Lectura: se ejecuta sin espera")
    if lvl == Level.C1:
        if origin not in ("user", "ui"):
            return Decision(lvl, "propose", "La instrucción no viene de ti (proviene de datos o del modelo): queda como propuesta")
        if ambiguous:
            return Decision(lvl, "propose", "Faltan datos o la instrucción es ambigua: queda como borrador")
        return Decision(lvl, "execute", "Cambio local reversible pedido por ti: se ejecuta y se puede deshacer")
    if lvl == Level.C2:
        return Decision(lvl, "awaiting_authorization", "Efecto externo o difícil de revertir: requiere autorización específica")
    return Decision(lvl, "needs_review", "Alto impacto o herramienta desconocida: no se automatiza")
