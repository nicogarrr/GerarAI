"""Pedido del propietario (2026-10-17): la respuesta visible del chat es
prosa natural en castellano; la estructura con citas va plegada. Y las
preguntas generales de inversion (Buffett y sus cartas) se responden con
la doctrina de la biblioteca en vez de abstenerse.
"""

import asyncio
import json
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.llm import LLMResponse, Message, Usage
from app.models.entities import Base, Company, FinancialFact
from app.schemas import ChatResponse
from app.services.chat_service import (
    KEY_FACT_METRICS,
    ChatService,
    _fmt_period_es,
    _fmt_value_es,
)
from app.services.chat_synthesis_service import (
    ChatSynthesisService,
    _general_scope,
    _prose_answer_valid,
)


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


def _company(db: Session, ticker: str = "ASTS") -> Company:
    company = Company(
        ticker=ticker, name="AST SpaceMobile", exchange="NASDAQ", currency="USD",
        sector="Telecom", industry="Satellites", company_type="growth",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def test_pregunta_doctrina_buffett_no_se_abstiene():
    # "sus cartas" son las de Buffett (tercero), no la cartera del usuario.
    scope = _general_scope(
        "Segun Warren Buffett y sus cartas cuales son las 3 cosas mas importantes para invertir"
    )
    assert scope == "inferred"


def test_su_cartera_sigue_siendo_ambito_privado():
    assert _general_scope("como va su cartera este mes") == "abstain"
    assert _general_scope("y sus posiciones?") == "abstain"


def test_prose_answer_rechaza_volcado_estructurado():
    assert not _prose_answer_valid("HECHO\n- revenue 391B [financial_fact:1]\n\nCALCULO\n- nada")
    assert not _prose_answer_valid("Ver news_event:153288 para el detalle")
    assert not _prose_answer_valid("Mira https://example.com para mas")
    assert not _prose_answer_valid("")
    assert not _prose_answer_valid("x" * 3000)
    assert not _prose_answer_valid("The company reported revenue and the margin is expanding")
    assert _prose_answer_valid(
        "ASTS cotiza a 63,45 USD (cierre del 16 oct 2026, Yahoo). "
        "Segun el 10-K del ejercicio 2025 (SEC), el flujo de caja operativo "
        "fue de -71,5 millones USD y el capex de unos 1.065 millones USD, "
        "asi que el flujo de caja libre ronda los -1.136 millones USD."
    )


def test_formatos_legibles_es():
    assert _fmt_value_es(-71_517_000, "USD") == "-71,52 millones USD"
    assert _fmt_value_es(-1_136_258_000, "USD") == "-1,14 mil millones USD"
    assert _fmt_value_es(2_335_683_000, "USD") == "2,34 mil millones USD"
    assert _fmt_value_es(None, "USD") == "sin dato"
    assert _fmt_period_es("2025-12-31:FY") == "ejercicio 2025"
    assert _fmt_period_es("2025-09-30:Q3") == "Q3 2025"


def test_cash_almacenado_no_aparece_como_faltante():
    # La ingesta guarda el efectivo como cash_and_equivalents; el chat lo
    # reconoce como dato clave presente (antes siempre faltaba "cash").
    assert "cash_and_equivalents" in KEY_FACT_METRICS
    assert "cash" not in KEY_FACT_METRICS
    db = _db()
    company = _company(db)
    db.add(FinancialFact(
        company_id=company.id, metric="cash_and_equivalents",
        value=Decimal("2335683000"), unit="USD", period="2025-12-31:FY",
        fiscal_year=2025, source_type="SEC", is_reported=True,
        confidence=Decimal("0.95"),
    ))
    db.commit()
    response = ChatService(StubProvider())._deterministic_answer(
        db, "ASTS", "company", "ASTS"
    )
    assert "efectivo y equivalentes 2,34 mil millones USD (ejercicio 2025, SEC)" in response.answer
    faltan = next((l for l in response.answer.split("\n\n") if l.startswith("Aun faltan")), "")
    assert "efectivo" not in faltan


def test_respuesta_determinista_es_prosa_natural():
    db = _db()
    company = _company(db)
    db.add(FinancialFact(
        company_id=company.id, metric="operating_cash_flow",
        value=Decimal("-71517000"), unit="USD", period="2025-12-31:FY",
        fiscal_year=2025, source_type="SEC", is_reported=True,
        confidence=Decimal("0.95"),
    ))
    db.commit()
    response = ChatService(StubProvider())._deterministic_answer(
        db, "ASTS", "company", "ASTS"
    )
    answer = response.answer
    assert "flujo de caja operativo -71,52 millones USD (ejercicio 2025, SEC)" in answer
    for label in ("HECHO", "CALCULO", "AFIRMACION", "FOTO DE EVIDENCIA", "news_event:", "financial_fact:"):
        assert label not in answer
    # La estructura sigue disponible plegada con sus citas.
    facts_section = next(s for s in response.sections if s.key == "facts")
    assert "financial_fact:" in facts_section.body


def test_general_con_doctrina_cita_cartas_de_la_biblioteca():
    provider = StubProvider(
        "En sus cartas, Buffett repite tres ideas: entender el negocio, "
        "comprar con margen de seguridad y pensar a largo plazo."
    )
    doctrine_source = {
        "type": "knowledge_chunk", "id": 7, "author": "Warren Buffett",
        "title": "Carta a accionistas 1996", "page_number": 12,
        "text": "Your goal as an investor should simply be to purchase...",
    }
    baseline = ChatResponse(answer="", sources=[doctrine_source])
    result = asyncio.run(
        ChatSynthesisService(provider).synthesize_general(
            question="Segun Buffett y sus cartas cuales son las 3 cosas mas importantes para invertir",
            baseline=baseline,
        )
    )
    assert result.model == "stub-model"
    assert result.answer.startswith("En sus cartas, Buffett")
    assert result.sources and result.sources[0]["author"] == "Warren Buffett"
    # La doctrina llego al prompt del modelo.
    payload = json.loads(provider.requests[0].messages[-1].content)
    assert payload["sources_available"] is True
    assert payload["doctrine_context"][0]["author"] == "Warren Buffett"
    assert result.llm_trace["doctrine_chunks"] == 1


def test_general_sin_doctrina_no_inventa_atribuciones():
    provider = StubProvider(
        "Segun el informe anual de Berkshire, lo importante es el circulo de competencia."
    )
    baseline = ChatResponse(answer="", sources=[])
    result = asyncio.run(
        ChatSynthesisService(provider).synthesize_general(
            question="que es el circulo de competencia de Buffett", baseline=baseline,
        )
    )
    # Sin doctrina del autor: no atribuir y ofrecer una alternativa útil.
    assert result.model == "deterministic"
    assert "fragmento verificable" in result.answer
    assert result.sources == []
    assert provider.requests == []


def test_memoria_visible_en_prosa_con_marcador():
    # Regresion CI research-evidence-flow: la pregunta pide recordar un
    # marcador y hay notas guardadas; la prosa visible debe incluirlas con
    # naturalidad (sin IDs ni etiquetas), no solo "no tengo hechos".
    from app.models.entities import MemoryItem

    marker = "e2e-evidence-test-123"
    db = _db()
    company = _company(db, ticker="MSFT")
    db.add(MemoryItem(
        tenant_id="tenant-test", company_id=company.id, scope="company",
        memory_type="watch_item", importance=9, status="active",
        content=f"Track Azure AI demand and the primary evidence marker {marker}.",
        source_type="user",
    ))
    db.commit()
    response = ChatService(StubProvider())._deterministic_answer(
        db,
        f"Remember {marker}; what evidence supports the Azure AI demand claim?",
        "company", "MSFT",
    )
    assert marker in response.answer
    # El cerebro es SOLO LECTURA: el "Remember ..." de la pregunta ya no
    # escribe memoria ni la prosa dice "Anotado"; solo cita las notas
    # guardadas previamente.
    assert "Anotado en tu memoria:" not in response.answer
    assert "notas guardadas" in response.answer
    assert db.query(MemoryItem).count() == 1
    for label in ("HECHO", "HIPOTESIS", "memory_item:", "memory_writeback:"):
        assert label not in response.answer
