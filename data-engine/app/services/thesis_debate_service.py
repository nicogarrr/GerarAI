"""Fase 'abogado del diablo': debate alcista/bajista + lentes de riesgo.

Referencia conceptual: TradingAgents (debate bull/bear + risk team
agresivo/conservador/neutral). Sin langgraph (no esta en el venv): la
orquestacion es una linea recta bull -> bear -> veredicto usando SIEMPRE
el provider LLM unico de la app (``app.llm.factory.create_llm_provider``).

Coste: ``debate_thesis`` = maximo 3 llamadas LLM (bull, bear, juez);
``risk_lenses`` = maximo 1 llamada LLM. Cualquier fallo del LLM degrada
a un veredicto determinista: nunca se propaga una excepcion.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.llm import LLMRequest, LLMResponse, Message
from app.llm.base import LLMProvider
from app.services.budget import BudgetController, BudgetExceededError
from app.services.jev_gates import (
    DEBATE_VERDICT_CRITERIA,
    DEBATE_VERDICT_INSTRUCTIONS,
    DEBATE_WORTHWHILE_CRITERIA,
    DEBATE_WORTHWHILE_INSTRUCTIONS,
    DEBATE_WORTHWHILE_THRESHOLD,
    jev_choice_or_none,
)
from app.services.llm_output_guard import complete_guarded
from app.services.prompt_registry import get_prompt

# Coste fijo por operacion (techo, solo si el LLM responde a todo).
LLM_CALLS_PER_DEBATE = 3
LLM_CALLS_PER_LENSES = 1

BULLISH_CUES = (
    "crecimiento",
    "growth",
    "moat",
    "ventaja",
    "margen",
    "margin",
    "rentabilidad",
    "upside",
    "oportunidad",
    "opportunity",
    "lider",
    "leader",
    "record",
    "recompra",
    "buyback",
    "dividendo",
    "expansi",
    "tailwind",
)
BEARISH_CUES = (
    "riesgo",
    "risk",
    "deuda",
    "debt",
    "caida",
    "decline",
    "perdida",
    "loss",
    "demanda debil",
    "weak",
    "competencia",
    "competition",
    "dilucion",
    "dilution",
    "downside",
    "amenaza",
    "threat",
    "recorte",
    "cut",
    "fraude",
    "fraud",
    "litigio",
)


def _resolve_provider(provider: LLMProvider | None) -> LLMProvider:
    if provider is not None:
        return provider
    from app.llm.factory import create_llm_provider

    return create_llm_provider()


def _record_spend(budget: BudgetController, db: Any, resp: LLMResponse, workflow: str) -> None:
    model = getattr(resp, "model", None) or "unknown"
    usage = resp.usage
    cost = budget.estimate_cost_eur(model, usage.input_tokens, usage.output_tokens)
    budget.record(db, model, workflow, cost, usage.total_tokens)


async def _complete_text(
    provider: LLMProvider,
    *,
    system: str,
    user: str,
    task: str,
    max_tokens: int,
    temperature: float,
    calls: list[int] | None = None,
    db: Any | None = None,
) -> tuple[str, LLMResponse | None]:
    budget = BudgetController() if db is not None else None
    # Cada llamada del debate gasta presupuesto del tenant: sin saldo no hay
    # llamada (el llamador ya degrada a la salida determinista).
    if budget is not None and not budget.can_spend(db, 0.02):
        raise BudgetExceededError("LLM budget exhausted")
    request = LLMRequest(
        messages=[Message("system", system), Message("user", user)],
        task=task,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=get_settings().reasoning_effort_for("debate"),
    )
    # Un texto con CJK, ingles mezclado o tokens corruptos se reintenta una vez;
    # si falla otra vez levanta LLMOutputRejected y el llamador degrada a la
    # salida determinista (nunca se publica el texto roto).
    def _tally(_resp: LLMResponse) -> None:
        # llm_calls cuenta TODAS las llamadas reales, tambien reintento y rechazo.
        if calls is not None:
            calls[0] += 1
        if budget is not None:
            _record_spend(budget, db, _resp, f"thesis_debate.{task}")

    guarded = await complete_guarded(
        provider, request, source=f"thesis_debate.{task}", on_response=_tally
    )
    response = guarded.response
    text = (response.text or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    return text, response


def _count_cues(text: str, cues: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(len(re.findall(r"\b" + re.escape(cue) + r"\b", lowered)) for cue in cues)


def _deterministic_verdict(ticker: str, thesis: str, bull_case: str, bear_case: str) -> dict[str, str]:
    """Veredicto sin LLM: compara senales alcistas/bajistas en el texto."""
    corpus = " ".join([thesis or "", bull_case or "", bear_case or ""])
    bull_hits = _count_cues(corpus, BULLISH_CUES)
    bear_hits = _count_cues(corpus, BEARISH_CUES)
    if bull_hits > bear_hits:
        verdict, rationale = (
            "bullish",
            f"Veredicto determinista para {ticker}: {bull_hits} senales alcistas frente a "
            f"{bear_hits} bajistas. Juez LLM no disponible; revisar el caso bajista antes de actuar.",
        )
    elif bear_hits > bull_hits:
        verdict, rationale = (
            "bearish",
            f"Veredicto determinista para {ticker}: {bear_hits} senales bajistas frente a "
            f"{bull_hits} alcistas. Juez LLM no disponible; no aumentar exposicion sin mas evidencia.",
        )
    else:
        verdict, rationale = (
            "neutral",
            f"Veredicto determinista para {ticker}: senales equilibradas "
            f"({bull_hits}/{bear_hits}). Juez LLM no disponible; faltan datos para decantarse.",
        )
    return {"verdict": verdict, "verdict_rationale": rationale}


def _deterministic_side(ticker: str, thesis: str, side: str) -> str:
    excerpt = (thesis or "").strip()[:400] or "tesis no disponible"
    if side == "bull":
        return (
            f"[Alcista determinista - LLM no disponible] Caso a favor de {ticker}: "
            f"{excerpt}. Pendiente de validar catalizadores con datos."
        )
    return (
        f"[Bajista determinista - LLM no disponible] Caso en contra de {ticker}: "
        f"{excerpt}. Riesgos sin cuantificar; exigir margen de seguridad."
    )


async def debate_thesis(
    ticker: str,
    thesis: str,
    *,
    provider: LLMProvider | None = None,
    materiality_score: int = 0,
    portfolio_weight: float = 0.0,
    use_jev: bool = True,
    skip_jev_gate: bool = False,
    strict_provider: bool = False,
    db: Any | None = None,
) -> dict[str, Any]:
    """Debate bull -> bear -> veredicto. Nunca lanza excepcion.

    Devuelve ``{ticker, bull_case, bear_case, verdict, verdict_rationale,
    llm_calls, degraded, model}`` con ``verdict`` en
    ``{bullish, bearish, neutral}``.

    Gates Jev (best-effort, sin key todo sigue igual):
    - gate ``debate_worthwhile``: si la tesis es ``clear_cut`` con
      confianza >= 0.8 se omite el debate LLM (ahorra hasta 3 llamadas).
    - juez Jev: el veredicto (bullish/bearish/neutral) lo emite Jev sobre
      los casos bull/bear y reemplaza la 3ª llamada LLM; si Jev no esta
      disponible o falla, el juez LLM actua como siempre.
    """
    llm = _resolve_provider(provider)
    ticker = (ticker or "UNKNOWN").strip().upper() or "UNKNOWN"
    thesis = (thesis or "").strip()
    calls_box = [0]
    degraded = False
    model: str | None = None
    jev_gate: dict[str, Any] | None = None
    jev_judge: dict[str, Any] | None = None

    if use_jev and not skip_jev_gate:
        gate = await jev_choice_or_none(
            name="debate_worthwhile",
            text=thesis,
            instructions=DEBATE_WORTHWHILE_INSTRUCTIONS,
            criteria=DEBATE_WORTHWHILE_CRITERIA,
        )
        if gate is not None:
            jev_gate = {"label": gate.label, "confidence": gate.confidence}
            if (
                gate.label == "clear_cut"
                and gate.confidence >= DEBATE_WORTHWHILE_THRESHOLD
            ):
                jev_gate["skipped_llm"] = True
                bull_case = _deterministic_side(ticker, thesis, "bull")
                bear_case = _deterministic_side(ticker, thesis, "bear")
                fallback = _deterministic_verdict(
                    ticker, thesis, bull_case, bear_case
                )
                return {
                    "ticker": ticker,
                    "bull_case": bull_case,
                    "bear_case": bear_case,
                    "verdict": fallback["verdict"],
                    "verdict_rationale": fallback["verdict_rationale"],
                    "llm_calls": 0,
                    "degraded": False,
                    "model": "deterministic",
                    "materiality_score": materiality_score,
                    "portfolio_weight": portfolio_weight,
                    "jev_gate": jev_gate,
                    "jev_judge": None,
                }

    try:
        bull_case, resp = await _complete_text(
            llm,
            system=get_prompt("thesis_debate_bull").text,
            user=f"Ticker: {ticker}\nTesis: {thesis or '(sin tesis aportada)'}",
            task="red_team",
            max_tokens=4000,
            temperature=0.3,
            calls=calls_box,
            db=db,
        )
        model = model or resp.model
    except Exception as exc:
        if strict_provider:
            raise exc
        degraded = True
        bull_case = _deterministic_side(ticker, thesis, "bull")

    try:
        bear_case, resp = await _complete_text(
            llm,
            system=get_prompt("thesis_debate_bear").text,
            user=(
                f"Ticker: {ticker}\nTesis: {thesis or '(sin tesis aportada)'}\n"
                f"Caso alcista previo: {bull_case[:800]}"
            ),
            task="red_team",
            max_tokens=4000,
            temperature=0.3,
            calls=calls_box,
            db=db,
        )
        model = model or resp.model
    except Exception as exc:
        if strict_provider:
            raise exc
        degraded = True
        bear_case = _deterministic_side(ticker, thesis, "bear")

    verdict: str | None = None
    verdict_rationale = ""
    if use_jev:
        judge = await jev_choice_or_none(
            name="verdict",
            text=(
                f"Ticker: {ticker}\nTesis: {thesis or '(sin tesis aportada)'}\n"
                f"ALCISTA: {bull_case[:1000]}\nBAJISTA: {bear_case[:1000]}"
            ),
            instructions=DEBATE_VERDICT_INSTRUCTIONS,
            criteria=DEBATE_VERDICT_CRITERIA,
        )
        if judge is not None and judge.label in {"bullish", "bearish", "neutral"}:
            verdict = judge.label
            verdict_rationale = (
                f"Juez Jev para {ticker}: {judge.label} "
                f"(confianza {judge.confidence:.2f}) a partir del caso "
                "alcista y el bajista."
            )
            jev_judge = {"label": judge.label, "confidence": judge.confidence}
    if verdict is None:
        try:
            judge_text, resp = await _complete_text(
                llm,
                system=get_prompt("thesis_debate_judge").text,
                user=(
                    f"Ticker: {ticker}\nTesis: {thesis or '(sin tesis aportada)'}\n"
                    f"ALCISTA: {bull_case[:1000]}\nBAJISTA: {bear_case[:1000]}"
                ),
                task="red_team",
                max_tokens=2000,
                temperature=0.1,
                calls=calls_box,
                db=db,
            )
            model = model or resp.model
            match = re.search(r"(bullish|bearish|neutral)", judge_text.lower())
            verdict = match.group(1) if match else None
            verdict_rationale = judge_text.strip()[:600]
        except Exception as exc:
            if strict_provider:
                raise exc
            verdict = None

    if verdict not in {"bullish", "bearish", "neutral"}:
        if strict_provider:
            raise ValueError("invalid debate verdict")
        degraded = True
        fallback = _deterministic_verdict(ticker, thesis, bull_case, bear_case)
        verdict = fallback["verdict"]
        if not verdict_rationale:
            verdict_rationale = fallback["verdict_rationale"]

    return {
        "ticker": ticker,
        "bull_case": bull_case,
        "bear_case": bear_case,
        "verdict": verdict,
        "verdict_rationale": verdict_rationale,
        "llm_calls": calls_box[0],
        "degraded": degraded,
        "model": model or "deterministic",
        "materiality_score": materiality_score,
        "portfolio_weight": portfolio_weight,
        "jev_gate": jev_gate,
        "jev_judge": jev_judge,
    }


def _deterministic_lenses(analysis: str) -> dict[str, str]:
    excerpt = (analysis or "").strip()[:400] or "analisis no disponible"
    return {
        "aggressive": (
            "[Agresivo determinista - LLM no disponible] Maximizar exposicion a los "
            f"catalizadores: {excerpt}. Dimensionar con stop amplio y revisión semanal."
        ),
        "neutral": (
            "[Neutral determinista - LLM no disponible] Mantener posición base y "
            f"esperar confirmación: {excerpt}. Rebalancear solo ante nueva evidencia."
        ),
        "conservative": (
            "[Conservador determinista - LLM no disponible] Reducir riesgo: tomar "
            f"beneficios parciales y exigir margen de seguridad sobre {excerpt}."
        ),
    }


async def risk_lenses(
    analysis: str,
    *,
    provider: LLMProvider | None = None,
    materiality_score: int = 0,
    portfolio_weight: float = 0.0,
    db: Any | None = None,
) -> dict[str, Any]:
    """Tres lentes de riesgo sobre un analisis. Nunca lanza excepcion.

    Devuelve ``{aggressive, neutral, conservative, llm_calls, degraded, model}``.
    """
    llm = _resolve_provider(provider)
    analysis = (analysis or "").strip()
    try:
        request = LLMRequest(
            messages=[
                Message("system", get_prompt("risk_three_lenses").text),
                Message("user", f"Analisis: {analysis or '(sin analisis aportado)'}"),
            ],
            task="red_team",
            temperature=0.2,
            max_tokens=4000,
            reasoning_effort=get_settings().reasoning_effort_for("debate"),
        )
        budget = BudgetController() if db is not None else None
        if budget is not None and not budget.can_spend(db, 0.02):
            raise BudgetExceededError("LLM budget exhausted")
        response = await llm.complete(request)
        if budget is not None:
            _record_spend(budget, db, response, "thesis_risk_lenses")
        text = (response.text or "").strip()
        if not text:
            raise ValueError("empty LLM response")
        lenses: dict[str, str] = {}
        for key, label in (("aggressive", "agresivo"), ("neutral", "neutral"), ("conservative", "conservador")):
            match = re.search(rf"{label}\s*:\s*(.+?)(?=(?:agresivo|neutral|conservador)\s*:|$)", text, re.IGNORECASE | re.DOTALL)
            if match and match.group(1).strip():
                lenses[key] = match.group(1).strip()[:600]
        if len(lenses) != 3:
            raise ValueError("incomplete risk lenses")
        return {
            **lenses,
            "llm_calls": 1,
            "degraded": False,
            "model": response.model,
            "materiality_score": materiality_score,
            "portfolio_weight": portfolio_weight,
        }
    except Exception:
        return {
            **_deterministic_lenses(analysis),
            "llm_calls": 0,
            "degraded": True,
            "model": "deterministic",
            "materiality_score": materiality_score,
            "portfolio_weight": portfolio_weight,
        }
