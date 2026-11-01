"""Tipos del equipo de expertos. Todo vive en el objeto de la corrida."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Mode = Literal["thesis", "chat"]
Stance = Literal["positive", "negative", "neutral"]
ReportStatus = Literal["ok", "no_data", "timeout", "error"]


@dataclass(frozen=True)
class RunContext:
    """Quién pregunta y sobre qué. Lo fija el servidor, nunca el modelo."""

    tenant_id: str
    user_id: str | None = None
    ticker: str | None = None
    question: str | None = None
    mode: Mode = "thesis"
    lang: str = "es"
    holds_position: bool = False


@dataclass(frozen=True)
class ToolOutput:
    """Resultado de una herramienta de lectura: datos + de dónde salen."""

    source: Mapping[str, str]
    data: Any


ToolFn = Callable[[RunContext], "ToolOutput | None | Awaitable[ToolOutput | None]"]


@dataclass(frozen=True)
class ToolSpec:
    """Herramienta de SOLO lectura. Recibe únicamente el RunContext."""

    name: str
    fn: ToolFn
    description: str = ""


@dataclass(frozen=True)
class Evidence:
    id: str
    tool: str
    expert: str
    source: Mapping[str, str]
    data: Any


@dataclass
class Claim:
    text: str
    numbers: tuple[float, ...] = ()
    citations: tuple[str, ...] = ()
    metric: str | None = None
    #: Motivo por el que se descartó (vacío = válida).
    reason: str = ""


@dataclass
class ExpertReport:
    expert: str
    status: ReportStatus
    summary: str = ""
    stance: Stance = "neutral"
    claims: list[Claim] = field(default_factory=list)
    dropped: list[Claim] = field(default_factory=list)
    llm_calls: int = 0
    prompt_version: str | None = None
    error: str | None = None
    tool_errors: list[str] = field(default_factory=list)


@dataclass
class TeamResult:
    context: RunContext
    plan: list[str]
    reports: list[ExpertReport]
    sources: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    verdict: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": asdict(self.context),
            "plan": list(self.plan),
            "reports": [asdict(r) for r in self.reports],
            "sources": list(self.sources),
            "conflicts": list(self.conflicts),
            "verdict": self.verdict,
        }
