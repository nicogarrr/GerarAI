"""Chat con el equipo de expertos para preguntas complejas (detrás de EXPERT_TEAM_ENABLED).

Solo entra una pregunta sobre UNA empresa que el coordinador reparte entre
≥2 expertos («riesgo y valoración de X»). Todo lo demás, y cualquier fallo
del equipo, sigue por la síntesis de siempre: con el flag apagado el chat no
cambia. Cada afirmación que se muestra ya pasó el validador de citas; las
fuentes son datos que una herramienta devolvió en ESTA corrida.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import current_language
from app.schemas.api import ChatResponse, SynthesisSection
from app.services.expert_team.coordinator import ExpertTeam
from app.services.expert_team.models import RunContext, TeamResult, ToolSpec
from app.services.expert_team.roster import default_experts
from app.services.expert_team.service import run_team

logger = logging.getLogger(__name__)

MIN_EXPERTS = 2
#: Tope propio del equipo en el chat; nunca más que lo que le queda a la petición.
CHAT_TEAM_TIMEOUT_S = 45.0
PROMPT_VERSION = "expert-team-chat-v1"

_LABELS = {
    "es": {
        "fundamental": "Fundamental", "valuation": "Valoración", "risk": "Riesgo",
        "news": "Noticias", "tax": "Fiscal",
        "no_data": "sin datos suficientes", "timeout": "no respondió a tiempo", "error": "no disponible",
        "conflicts": "Choques entre expertos", "verdict": "Veredicto del juez",
        "stance": "{pos} lo ven a favor y {neg} en contra",
        "metric": "{metric}: cifras distintas según el experto",
        "labels": {"bullish": "a favor", "bearish": "en contra", "neutral": "neutral"},
    },
    "en": {
        "fundamental": "Fundamentals", "valuation": "Valuation", "risk": "Risk",
        "news": "News", "tax": "Tax",
        "no_data": "not enough data", "timeout": "did not answer in time", "error": "unavailable",
        "conflicts": "Disagreements between experts", "verdict": "Judge's verdict",
        "stance": "{pos} lean positive and {neg} negative",
        "metric": "{metric}: different figures depending on the expert",
        "labels": {"bullish": "positive", "bearish": "negative", "neutral": "neutral"},
    },
}


def _enabled() -> bool:
    from app.core.config import get_settings

    return bool(get_settings().expert_team_enabled)


def plan_for(question: str, ticker: str | None) -> list[str]:
    """Plan determinista del coordinador para el chat (sin herramientas ni LLM)."""
    ctx = RunContext(tenant_id=None, user_id=None, ticker=ticker, question=question, mode="chat")
    experts = default_experts()
    # plan() no ejecuta herramientas: basta con declararlas para el roster.
    tools = {name: ToolSpec(name, _no_tool) for spec in experts for name in spec.tools}
    return ExpertTeam(experts, tools, _never).plan(ctx)


async def _never(*_args: Any) -> str:  # pragma: no cover - plan() no razona
    raise AssertionError("plan() no llama al LLM")


def _no_tool(_ctx: RunContext) -> list[Any]:  # pragma: no cover - plan() no lee datos
    raise AssertionError("plan() no ejecuta herramientas")


def wants_team(question: str, ticker: str | None) -> bool:
    if not ticker or not _enabled():
        return False
    return len(plan_for(question, ticker)) >= MIN_EXPERTS


_TABLES = {
    "es": {
        "financial_facts": "Estados financieros", "valuation_engine": "Motor de valoración",
        "thesis_versions": "Tesis guardada", "risk_events": "Aviso de riesgo", "positions": "Tu cartera",
        "news_events": "Noticia", "code:tax_irpf_filing.savings_bands": "Tramos del IRPF del ahorro",
    },
    "en": {
        "financial_facts": "Financial statements", "valuation_engine": "Valuation engine",
        "thesis_versions": "Saved thesis", "risk_events": "Risk alert", "positions": "Your portfolio",
        "news_events": "News", "code:tax_irpf_filing.savings_bands": "IRPF (Spanish income tax) savings bands",
    },
}


def _source_label(src: dict[str, Any], lang: str = "es") -> str:
    """Etiqueta legible: qué dato, de dónde y de qué fecha (sin ids internos)."""
    tables = _TABLES.get(lang, _TABLES["es"])
    table = str(src.get("table") or src.get("tool") or "")
    parts = [tables.get(table, table)]
    for key in ("source", "period", "date", "law"):
        value = str(src.get(key) or "").strip()
        if value and value != "-" and value not in parts:
            parts.append(value)
    return " · ".join(p for p in parts if p)


def render(result: TeamResult, lang: str) -> ChatResponse | None:
    """Secciones por experto + fuentes numeradas. None si no queda ninguna afirmación válida."""
    t = _LABELS.get(lang, _LABELS["es"])
    numbers = {src["id"]: n for n, src in enumerate(result.sources, start=1)}
    sections: list[SynthesisSection] = []
    lines: list[str] = []
    for report in result.reports:
        name = t.get(report.expert, report.expert)
        valid = [c for c in report.claims if not c.reason]
        if not valid:
            reason = t.get(report.status if report.status != "ok" else "no_data", t["no_data"])
            sections.append(SynthesisSection(key="insufficient_data", body=f"{name}: {reason}"))
            lines.append(f"**{name}**: {reason}.")
            continue
        bullets = []
        cites: list[str] = []
        for claim in valid:
            refs = [f"[{numbers[c]}]" for c in claim.citations if c in numbers]
            bullets.append(f"- {claim.text} {' '.join(refs)}".rstrip())
            cites.extend(c for c in claim.citations if c in numbers and c not in cites)
        summary = f": {report.summary}" if report.summary else ""
        sections.append(SynthesisSection(key="facts", body="\n".join([name + summary, *bullets]), citations=cites))
        lines.append("\n".join([f"**{name}**{summary}", *bullets]))
    if not any(s.key == "facts" for s in sections):
        return None
    if result.conflicts:
        notes = []
        for conflict in result.conflicts:
            if conflict.get("type") == "stance":
                pos = ", ".join(t.get(e, e) for e in conflict.get("positive", []))
                neg = ", ".join(t.get(e, e) for e in conflict.get("negative", []))
                notes.append(t["stance"].format(pos=pos, neg=neg))
            else:
                notes.append(t["metric"].format(metric=conflict.get("metric", "")))
        body = f"{t['conflicts']}: " + "; ".join(notes)
        sections.append(SynthesisSection(key="contradictions", body=body))
        lines.append(body)
    if result.verdict and result.verdict.get("source") == "judge":
        label = t["labels"].get(result.verdict.get("label", ""), result.verdict.get("label", ""))
        body = f"{t['verdict']}: {label}. {result.verdict.get('rationale', '')}".strip()
        sections.append(SynthesisSection(key="conclusion", body=body))
        lines.append(body)
    # Las fuentes viajan en «sources» (el chat las pinta en su lista «Fuentes»
    # con el mismo número [n] que lleva cada afirmación).
    answer = "\n\n".join(lines)
    # «title» es lo que el chat del frontend muestra en «Fuentes».
    sources = [
        {**src, "type": "expert_evidence", "n": numbers[src["id"]], "title": f"[{numbers[src['id']]}] {_source_label(src, lang)}"}
        for src in result.sources
    ]
    return ChatResponse(
        answer=answer,
        sections=sections,
        sources=sources,
        prompt_version=PROMPT_VERSION,
        model="expert_team",
        confidence=0.7,
        llm_trace={"expert_team": {
            "plan": list(result.plan),
            "status": {r.expert: r.status for r in result.reports},
            "dropped": sum(len(r.dropped) for r in result.reports),
            "conflicts": len(result.conflicts),
        }},
    )


async def answer_with_team(
    db: Session, question: str, ticker: str, provider: Any, *, deadline_s: float | None = None
) -> ChatResponse | None:
    """Respuesta del equipo o None (el chat sigue por la síntesis de siempre)."""
    timeout = CHAT_TEAM_TIMEOUT_S if deadline_s is None else max(0.0, min(CHAT_TEAM_TIMEOUT_S, deadline_s))
    if timeout <= 0:
        return None
    try:
        result = await asyncio.wait_for(
            run_team(db, ticker=ticker, mode="chat", question=question, provider=provider), timeout=timeout
        )
        return render(result, current_language())
    except Exception as exc:  # noqa: BLE001 — el equipo nunca rompe el chat
        logger.warning("expert_team.chat_fallback", extra={"error": type(exc).__name__})
        return None
