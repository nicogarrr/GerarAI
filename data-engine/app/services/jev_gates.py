"""Micro-gates TypeSafe Jev delante del LLM principal.

Jev no genera texto: responde preguntas tipadas con probabilidades
calibradas a ~$0.042/Mtok de entrada. Cada gate es best-effort:

- Sin ``TYPESAFE_API_KEY`` (``build_client()`` -> None) o ante cualquier
  fallo/red, el helper devuelve ``None`` (o "conservar todo" en KPI) y el
  flujo sigue su camino actual sin cambios.
- Como maximo 1 llamada Jev extra por flujo. Excepcion: ``debate_thesis``
  combina gate (1) + juez (1) = 2 llamadas Jev a cambio de ahorrar hasta
  3 llamadas LLM.

Los callers async usan ``await`` sobre ``JevDecisionClient``; los callers
sync (``NewsService._analyze_news``, ``ClaimIntelligenceService``) usan los
helpers ``*_sync`` de este modulo (``asyncio.run`` interno, mismo patron que
``jev_triage_service.classify_urgency_sync``).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any

from app.llm.jev import JevCreditExhausted, JevDecision
from app.services.async_bridge import run_from_any_context
from app.services.jev_availability import credit_status, mark_credit_exhausted
from app.services.jev_triage_service import build_client

logger = logging.getLogger("gerarai.jev_gates")

# Umbrales de confianza calibrada para actuar sobre el veredicto de Jev.
DEBATE_WORTHWHILE_THRESHOLD = 0.8
NEWS_ACTION_THRESHOLD = 0.85
CHAT_BASELINE_OK_THRESHOLD = 0.8
# Un chunk "noise" con confianza menor se conserva: solo se filtra ruido
# seguro, nunca se ahorra el LLM ante la duda.
KPI_NOISE_CONFIDENCE = 0.6
KPI_CHUNK_CHARS = 800
KPI_MAX_QUESTIONS = 30

DEBATE_WORTHWHILE_INSTRUCTIONS = (
    "Is this investment thesis worth a full bull-vs-bear debate, or is it "
    "already clear-cut (factual, trivial, settled, or too thin to debate)?"
)
DEBATE_WORTHWHILE_CRITERIA = {
    "contestable": (
        "genuine disagreement is possible; bull and bear cases would differ "
        "materially; thesis is vague, disputed, or high-stakes"
    ),
    "clear_cut": (
        "thesis is purely factual, trivial, already settled, or so thin that "
        "a bull/bear debate adds nothing"
    ),
}

DEBATE_VERDICT_INSTRUCTIONS = (
    "You are the neutral judge. Read the bullish case and the bearish case "
    "for this ticker and return a single-word verdict."
)
DEBATE_VERDICT_CRITERIA = {
    "bullish": "upside evidence and catalysts outweigh the downside risks",
    "bearish": "downside risks and weaknesses outweigh the upside case",
    "neutral": "evidence is balanced or insufficient to lean either way",
}

NEWS_ACTION_INSTRUCTIONS = (
    "How should an investment tracker handle this news item given a stream "
    "of recent market coverage?"
)
NEWS_ACTION_CRITERIA = {
    "new_fact": (
        "contains new, potentially price-relevant information not seen before"
    ),
    "duplicate": (
        "repeats already-known facts; no new information versus recent coverage"
    ),
    "noise": (
        "opinion piece, generic market commentary, promo, or content without "
        "actionable facts"
    ),
}

CHAT_NEEDS_LLM_INSTRUCTIONS = (
    "Does this investor question need LLM synthesis over stored context, or "
    "is the retrieved deterministic context already a complete answer?"
)
CHAT_NEEDS_LLM_CRITERIA = {
    "needs_llm": (
        "question needs synthesis, comparison, judgment, or composing "
        "scattered evidence into an answer"
    ),
    "baseline_ok": (
        "simple factual lookup fully answered by stored context; an LLM "
        "synthesis layer would add nothing"
    ),
}

KPI_SIGNAL_INSTRUCTIONS = (
    "Does this document excerpt explicitly report a company KPI with a value "
    "and a period (revenue, margin, subscribers, backlog, guidance, ...)?"
)
KPI_SIGNAL_CRITERIA = {
    "signal": (
        "excerpt explicitly reports a company KPI figure with value and period"
    ),
    "noise": (
        "no explicitly reported KPI; generic text, opinion, or boilerplate"
    ),
}

CLAIM_RELATION_INSTRUCTIONS = (
    "Compare the new statement against the historical claim. How does the "
    "new statement relate to the old claim?"
)
CLAIM_RELATION_CRITERIA = {
    "supported": "new statement confirms or closely matches the old claim",
    "contradicted": "new statement materially conflicts with the old claim",
    "superseded": "new statement explicitly revises or replaces the old claim",
    "stale": "old claim expired or is no longer applicable",
}


async def jev_choice_or_none(
    *,
    name: str,
    text: str,
    instructions: str,
    criteria: dict[str, str],
    max_chars: int = 2000,
) -> JevDecision | None:
    """Una clasificación acotada; falla cerrado al flujo preexistente."""
    state = credit_status()["status"]
    if state in {"fallback_proveedor_alternativo", "desactivado_sin_credito", "estado_no_disponible"}:
        return None
    try:
        client = build_client()
        if client is None:
            return None
        decision = await client.classify(
            (text or "")[:max_chars], name=name,
            instructions=instructions, criteria=criteria,
        )
        # Nunca aceptar etiquetas desconocidas o confidencias fuera de rango.
        if decision.label not in criteria or not math.isfinite(decision.confidence) or not 0 <= decision.confidence <= 1:
            return None
        return decision
    except JevCreditExhausted:
        mark_credit_exhausted()
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("jev gate %s failed: %s", name, exc)
        return None


def jev_choice_sync(
    *,
    name: str,
    text: str,
    instructions: str,
    criteria: dict[str, str],
    max_chars: int = 2000,
) -> JevDecision | None:
    """Puente sync seguro cuando el llamador ya ejecuta un event loop."""
    return run_from_any_context(jev_choice_or_none(
        name=name, text=text, instructions=instructions,
        criteria=criteria, max_chars=max_chars,
    ))


def jev_news_action_sync(text: str) -> JevDecision | None:
    """Gate (3): new_fact / duplicate / noise para NewsService._analyze_news."""
    return jev_choice_sync(
        name="news_action",
        text=text,
        instructions=NEWS_ACTION_INSTRUCTIONS,
        criteria=NEWS_ACTION_CRITERIA,
    )


def jev_claim_relation_sync(claim_text: str, candidate_text: str) -> JevDecision | None:
    """Gate (6): solo se llama desde la rama `uncertain` de classify_relation."""
    combined = f"HISTORICAL CLAIM: {claim_text or ''}\nNEW STATEMENT: {candidate_text or ''}"
    return jev_choice_sync(
        name="claim_relation",
        text=combined,
        instructions=CLAIM_RELATION_INSTRUCTIONS,
        criteria=CLAIM_RELATION_CRITERIA,
    )


async def kpi_chunk_keep_flags(texts: Sequence[str]) -> list[bool] | None:
    """Gate (2): pre-filtro kpi_signal por chunk en UNA sola llamada systemone.

    Devuelve un flag por chunk (True = conservar). None si Jev no esta
    disponible o falla -> el caller conserva todos los chunks (sin cambios).
    Ante la duda se conserva: solo el ruido seguro (noise con confianza
    >= KPI_NOISE_CONFIDENCE) se filtra.
    """
    previews = [(text or "")[:KPI_CHUNK_CHARS] for text in texts]
    if not previews:
        return []
    try:
        client = build_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("jev gate kpi_signal: no client (%s)", exc)
        return None
    if client is None or credit_status()["status"] != "activo":
        return None
    n_asked = min(len(previews), KPI_MAX_QUESTIONS)
    questions: dict[str, dict[str, Any]] = {
        f"chunk_{i}": {
            "type": "choice",
            "instructions": f"Excerpt {i}. {KPI_SIGNAL_INSTRUCTIONS}",
            "criteria": dict(KPI_SIGNAL_CRITERIA),
        }
        for i in range(n_asked)
    }
    state = {
        "task": "kpi_prefilter",
        "excerpts": [{"index": i, "text": previews[i]} for i in range(n_asked)],
    }
    try:
        result = await client.systemone(state, questions)
    except JevCreditExhausted:
        mark_credit_exhausted()
        return None
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("jev gate kpi_signal failed: %s", exc)
        return None
    answers = (result.get("answers") or {}) if isinstance(result, dict) else {}
    flags: list[bool] = []
    for i in range(n_asked):
        answer = answers.get(f"chunk_{i}") or {}
        label = str(answer.get("choice") or "").lower()
        try:
            confidence = float(answer.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if label == "signal":
            flags.append(True)
        elif label == "noise" and confidence >= KPI_NOISE_CONFIDENCE:
            flags.append(False)
        else:
            flags.append(True)  # dudoso o respuesta inesperada: conservar
    flags.extend([True] * (len(previews) - n_asked))
    return flags

# Etiquetas auxiliares: nunca determinan si una noticia se ingiere, si un
# ticket se acepta, si una alerta se envía, o si una tesis se regenera.
UNIVERSE_RELEVANCE_CRITERIA = {
    "tracked": "Directly relevant to an existing portfolio position or watchlist name",
    "universe": "Market-universe coverage without direct tracked-position relevance",
}
TICKET_CRITERIA = {
    "observed": "A dated observation supported by a named primary source",
    "scenario": "A conditional what-if projection, not a confirmed fact",
    "hypothesis": "An interpretation requiring independent evidence or review",
}
DIGEST_CRITERIA = {
    "same_fact": "Same dated event corroborated by another source",
    "distinct": "Separate event, or different date/claim even when same ticker",
}
THESIS_CRITERIA = {
    "substantive": "New material facts or evidence require thesis review",
    "trivial": "Only a formatting or small nonmaterial change; do not treat as verified",
}
CLAIM_ROUTING_CRITERIA = {
    "verifiable": "Explicit, dated, externally checkable claim",
    "narrative": "Interpretation, valuation judgment or scenario, not a checked fact",
}
ANOMALY_CRITERIA = {
    "flag": "Possible discrepancy or anomalous value; requires source verification",
    "ordinary": "No obvious discrepancy in the supplied context",
}


def mark_only(name: str, text: str, instructions: str, criteria: dict[str, str], threshold: float = .85) -> dict | None:
    """Metadata-only classification. A failure or low confidence is no mark."""
    decision = jev_choice_sync(name=name, text=text, instructions=instructions, criteria=criteria)
    if decision is None or decision.label not in criteria or not math.isfinite(decision.confidence) or not threshold <= decision.confidence <= 1:
        return None
    return {"label": decision.label, "confidence": round(decision.confidence, 4),
            "backend": getattr(decision, "backend", "jev")}
