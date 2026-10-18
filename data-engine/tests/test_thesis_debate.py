"""Tests hermeticos de la fase 'abogado del diablo'.

Sin red: el provider LLM siempre se sustituye por dobles en memoria.
"""

import asyncio

from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, LLMResponse, Message, Usage
from app.llm.routing import TaskModelRouter
from app.schemas import ChatResponse
from app.services.chat_synthesis_service import ChatSynthesisService
from app.services.thesis_debate_service import (
    LLM_CALLS_PER_DEBATE,
    LLM_CALLS_PER_LENSES,
    debate_thesis,
    risk_lenses,
)


class ScriptedProvider(LLMProvider):
    """Devuelve respuestas guionizadas en orden; cuenta las llamadas."""

    name = "scripted-test-provider"

    def __init__(self, script: list[str]):
        super().__init__(
            model_router=TaskModelRouter(default_model="test-model"),
            timeout_seconds=1,
            max_retries=0,
        )
        self.script = list(script)
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        text = self.script[min(self.calls - 1, len(self.script) - 1)]
        return LLMResponse(
            message=Message("assistant", text),
            usage=Usage(10, 10, 20),
            model="test-model",
            provider=self.name,
            request_id="test-request",
        )


class FailingProvider(LLMProvider):
    name = "failing-test-provider"

    def __init__(self):
        super().__init__(
            model_router=TaskModelRouter(default_model="test-model"),
            timeout_seconds=1,
            max_retries=0,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("LLM caido (simulado)")


def test_debate_thesis_happy_path_usa_tres_llamadas():
    provider = ScriptedProvider(
        [
            "Caso alcista: crecimiento de margenes y recompra de acciones.",
            "Caso bajista: riesgo de deuda elevada y competencia intensa.",
            "VEREDICTO: bearish | La deuda pesa mas que el crecimiento.",
        ]
    )
    result = asyncio.run(debate_thesis("SAN", "Tesis de prueba", provider=provider))
    assert result["ticker"] == "SAN"
    assert "alcista" in result["bull_case"].lower()
    assert "bajista" in result["bear_case"].lower()
    assert result["verdict"] == "bearish"
    assert result["degraded"] is False
    assert result["llm_calls"] == LLM_CALLS_PER_DEBATE == 3
    assert provider.calls == 3


def test_debate_thesis_degrada_a_veredicto_determinista_si_falla_llm():
    result = asyncio.run(
        debate_thesis("BBVA", "Crecimiento con riesgo de deuda", provider=FailingProvider())
    )
    assert result["verdict"] in {"bullish", "bearish", "neutral"}
    assert result["bull_case"] and result["bear_case"]
    assert result["verdict_rationale"]
    assert result["degraded"] is True
    assert result["llm_calls"] == 0
    assert result["model"] == "deterministic"


def test_debate_thesis_juez_invalido_cae_a_determinista():
    provider = ScriptedProvider(
        [
            "Todo es crecimiento y oportunidad.",
            "Pero hay riesgo de deuda y perdidas.",
            "No me decanto por nada en concreto.",  # sin palabra de veredicto
        ]
    )
    result = asyncio.run(debate_thesis("TEF", "Tesis mixta", provider=provider))
    assert result["verdict"] in {"bullish", "bearish", "neutral"}
    assert result["degraded"] is True
    assert result["llm_calls"] == 3  # el juez consumio llamada aunque fue inservible


def test_risk_lenses_happy_path_una_llamada():
    provider = ScriptedProvider(
        ["AGRESIVO: duplicar posicion. NEUTRAL: mantener y esperar. CONSERVADOR: recortar a la mitad."]
    )
    result = asyncio.run(risk_lenses("Analisis de prueba", provider=provider))
    assert result["aggressive"] and result["neutral"] and result["conservative"]
    assert result["degraded"] is False
    assert result["llm_calls"] == LLM_CALLS_PER_LENSES == 1


def test_risk_lenses_degrada_sin_llm():
    result = asyncio.run(risk_lenses("Analisis de prueba", provider=FailingProvider()))
    assert result["aggressive"] and result["neutral"] and result["conservative"]
    assert result["degraded"] is True
    assert result["llm_calls"] == 0


def test_enganche_chat_opcional_no_rompe_el_flujo():
    baseline = ChatResponse(answer="Respuesta base", sources=[])
    # 1) Desactivado por defecto: el flujo actual queda intacto.
    out = asyncio.run(
        ChatSynthesisService(FailingProvider()).synthesize(
            question="Que opinas de SAN?",
            ticker="SAN",
            baseline=baseline,
        )
    )
    assert out.model == "deterministic"
    assert "thesis_debate" not in out.llm_trace
    # 2) Activado explicito con LLM caido: tampoco rompe (el sintetizador
    # degrada a la respuesta determinista; el debate solo se adjunta en la
    # rama de exito, asi que aqui simplemente no aparece).
    baseline2 = ChatResponse(answer="Respuesta base", sources=[])
    out2 = asyncio.run(
        ChatSynthesisService(FailingProvider()).synthesize(
            question="Que opinas de SAN?",
            ticker="SAN",
            baseline=baseline2,
            enable_debate=True,
        )
    )
    assert out2.model == "deterministic"


def _budget_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.entities import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    return session


def test_debate_with_db_records_budget_usage_per_call():
    from sqlalchemy import func, select

    from app.models.entities import BudgetUsage

    db = _budget_db()
    provider = ScriptedProvider(
        [
            "Caso alcista: crecimiento de margenes y recompra de acciones.",
            "Caso bajista: riesgo de deuda elevada y competencia intensa.",
            "VEREDICTO: bearish | La deuda pesa mas que el crecimiento.",
        ]
    )
    result = asyncio.run(debate_thesis("SAN", "Tesis de prueba", provider=provider, db=db))
    assert result["llm_calls"] == 3
    rows = db.scalar(select(func.count()).select_from(BudgetUsage))
    assert rows == 3


def test_debate_with_exhausted_budget_makes_no_llm_calls():
    from datetime import date
    from decimal import Decimal

    from app.core.config import get_settings
    from app.models.entities import BudgetUsage

    db = _budget_db()
    db.add(
        BudgetUsage(
            usage_date=date.today(), model="m", workflow="w",
            cost_eur=Decimal(str(get_settings().llm_daily_cap_eur + 1)), token_count=1,
        )
    )
    db.commit()
    provider = ScriptedProvider(["x", "y", "VEREDICTO: bullish"])
    result = asyncio.run(debate_thesis("SAN", "Tesis de prueba", provider=provider, db=db))
    assert provider.calls == 0
    assert result["degraded"] is True
    assert result["llm_calls"] == 0
    assert result["model"] == "deterministic"
