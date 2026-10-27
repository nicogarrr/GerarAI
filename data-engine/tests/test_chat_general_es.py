"""Router de intencion del chat: small talk natural ES + general con LLM.

Decidido por main bajo preferencias del propietario (cero terminal / secretos
fuera de chat): el asistente responde a TODO con naturalidad en espanol;
la estructura HECHO/CALCULO/... es solo para respuestas de datos con ticker.
"""

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.llm import LLMResponse, Message, Usage
from app.models.entities import Base
from app.schemas import ChatResponse
from app.services.chat_service import _SMALL_TALK_RE, ChatService
from app.services.chat_synthesis_service import ChatSynthesisService
from app.services.prompt_registry import get_prompt


class StubProvider:
    name = "stub"

    def __init__(self, text: str = "Respuesta natural."):
        self.text = text
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            message=Message("assistant", self.text),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
            model="stub-model",
            provider="stub",
            request_id="req-1",
        )


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = "tenant-test"
    return session


def test_small_talk_regex_solo_saludos_puros():
    assert _SMALL_TALK_RE.match("hola")
    assert _SMALL_TALK_RE.match("Buenas tardes!")
    assert _SMALL_TALK_RE.match("muchas gracias")
    assert not _SMALL_TALK_RE.match("hola, como va ASTS?")
    assert not _SMALL_TALK_RE.match("que es el PER")


def test_small_talk_respuesta_natural_sin_llm():
    db = _db()
    provider = StubProvider()
    response = asyncio.run(
        ChatService(provider).answer(db, "hola", "portfolio", None)
    )
    assert response.model == "small-talk"
    assert "GerarAI" in response.answer and "CavaAI" not in response.answer
    assert "FACT" not in response.answer
    assert response.sources == []
    assert provider.requests == [], "small talk NO debe llamar al LLM"


def test_concepto_revisado_sin_ticker_es_local_en_espanol():
    db = _db()
    provider = StubProvider(text="El PER es el precio entre beneficios.")
    response = asyncio.run(
        ChatService(provider).answer(db, "que es el PER", "portfolio", None, use_jev=False)
    )
    assert not provider.requests
    from app.llm.general_concepts import DEFINITIONS
    assert response.answer == DEFINITIONS["PER"]
    assert response.prompt_version == "local-glossary-v1"


def test_synthesize_general_no_inventa_si_vacio():
    provider = StubProvider(text="   ")
    baseline = ChatResponse(answer="", sources=[])
    result = asyncio.run(
        ChatSynthesisService(provider).synthesize_general(
            question="hola que hay", baseline=baseline
        )
    )
    assert "No puedo responderte con fuentes ahora mismo" in result.answer
    assert result.model == "fallback"
    assert result.llm_trace["fallback"] is True


def test_prompt_chat_general_registrado():
    prompt = get_prompt("chat_general")
    assert prompt.version == "chat-general-v4"
    assert "cifras" in prompt.text


def test_precio_mercado_conectado_como_fuente_con_ticker():
    from decimal import Decimal

    from app.models.entities import Company, MarketPrice

    db = _db()
    company = Company(
        ticker="ASTS", name="AST", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Sat", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(MarketPrice(
        company_id=company.id, date=__import__("datetime").date(2026, 10, 9),
        open=Decimal("50"), high=Decimal("55"), low=Decimal("49"),
        close=Decimal("52.34"), adj_close=None,
    ))
    db.commit()
    response = ChatService()._deterministic_answer(db, "precio de ASTS", "company", "ASTS")
    price_sources = [s for s in response.sources if s["type"] == "market_price"]
    assert len(price_sources) == 1
    src = price_sources[0]
    assert "$52.34" in src["title"] and "2026-10-09" in src["title"]
    assert src["currency"] == "USD"
    assert src["price"] == "52.340000"
    assert src["adjusted"] is False, "adj_close NULL = spot sin ajustar, etiquetado"


def test_market_price_es_citable_en_secciones_grounded():
    from app.services.chat_synthesis_service import SECTION_SOURCE_TYPES

    assert "market_price" in SECTION_SOURCE_TYPES["facts"]
    assert "market_price" in SECTION_SOURCE_TYPES["calculations"]


def test_general_provenance_uses_response_not_wrapper_name():
    class Wrapper(StubProvider):
        name = "chat-independent-fallback"

        async def complete(self, request):
            response = await super().complete(request)
            from dataclasses import replace
            return replace(response, model="openai/gpt-oss-120b", provider="groq")

    result = asyncio.run(ChatSynthesisService(Wrapper("El PER compara precio y beneficios.")).synthesize_general(
        question="Cuéntame un chiste", baseline=ChatResponse(answer="", sources=[]),
    ))
    assert result.model == "openai/gpt-oss-120b"
    assert result.llm_trace["provider"] == "groq"
