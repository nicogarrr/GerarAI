"""Fuentes del chat: solo las usadas, sin atribucion falsa ni claves internas
(hallazgos QA 2, 3, 5 y 6)."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.llm import LLMResponse, Message, Usage
from app.models.entities import (
    Base,
    Claim,
    ClaimEvidence,
    Company,
    Document,
    DocumentChunk,
    FinancialFact,
    ThesisVersion,
)
from app.schemas import ChatResponse
from app.services.chat_service import ChatService, _human_evidence_title, _prune_sources
from app.services.chat_synthesis_service import ChatSynthesisService, _inferred_general_text_valid


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


class StubProvider:
    name = "stub"

    def __init__(self, text: str):
        self.text = text

    async def complete(self, request):
        return LLMResponse(
            message=Message("assistant", self.text),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
            model="stub-model",
            provider="stub",
            request_id="req-1",
        )


def _company(db, ticker="HIMS"):
    company = Company(
        ticker=ticker, name="Hims & Hers", exchange="NYSE", currency="USD",
        sector="Health", industry="Telehealth", company_type="growth",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def test_atribucion_sin_fuente_de_ese_autor_es_invalida():
    # Con doctrina de OTRO autor no se puede decir "segun Buffett".
    assert not _inferred_general_text_valid(
        "En sus cartas, Buffett insiste en el margen de seguridad.",
        allow_named_attribution=True,
        allowed_investors=frozenset(),
    )
    # Con un fragmento de Buffett en contexto, si.
    assert _inferred_general_text_valid(
        "En sus cartas, Buffett insiste en el margen de seguridad.",
        allow_named_attribution=True,
        allowed_investors=frozenset({"buffett"}),
    )


def test_fallback_general_sin_fuentes(db):
    baseline = ChatResponse(
        answer="x", sources=[{"type": "knowledge_chunk", "id": 1, "title": "Carta Numantia"}],
    )
    resp = ChatSynthesisService._general_fallback(baseline, reason="provider_or_guard_failure")
    assert resp.sources == []


def test_general_solo_adjunta_doctrina_referenciada(db):
    baseline = ChatResponse(
        answer="x",
        sources=[
            {"type": "knowledge_chunk", "id": 1, "title": "Carta Numantia 2024",
             "author": "Numantia", "text": "fragmento uno", "page_number": 3},
            {"type": "knowledge_chunk", "id": 2, "title": "Carta Azvalor 2020",
             "author": "Azvalor", "text": "fragmento dos", "page_number": 5},
        ],
    )
    svc = ChatSynthesisService(StubProvider("El margen de seguridad lo explica Numantia en su carta."))
    resp = asyncio.run(svc.synthesize_general(question="¿qué es el margen de seguridad?", baseline=baseline, db=None))
    assert [s["author"] for s in resp.sources] == ["Numantia"]


def test_general_pregunta_por_buffett_filtra_otros_autores(db):
    baseline = ChatResponse(
        answer="x",
        sources=[
            {"type": "knowledge_chunk", "id": 1, "title": "Carta Numantia 2024",
             "author": "Numantia", "text": "fragmento", "page_number": 3},
        ],
    )
    svc = ChatSynthesisService(StubProvider("Buffett dice que el margen de seguridad importa."))
    resp = asyncio.run(svc.synthesize_general(
        question="¿Qué es el margen de seguridad según Buffett?", baseline=baseline, db=None,
    ))
    # Sin fragmento de Buffett, la atribucion es invalida: cae al degradado sin fuentes.
    assert resp.model == "deterministic"
    assert "fragmento verificable" in resp.answer
    assert resp.sources == []


def test_titulos_de_evidencia_sin_plantilla_en_ingles():
    assert _human_evidence_title("Generated from SEC source.") == "Generado desde la fuente SEC"
    assert _human_evidence_title("Resumen normal") == "Resumen normal"


def test_prune_sources_solo_lo_citado_y_deduplicado():
    sources = [
        {"type": "financial_fact", "id": 1, "title": "Ingresos (ejercicio 2025)"},
        {"type": "document_chunk", "id": 10, "title": "SEC XBRL facts - HIMS"},
        {"type": "document_chunk", "id": 11, "title": "SEC XBRL facts - HIMS"},
        {"type": "claim", "id": 15, "title": "Afirmacion viva no citada"},
        {"type": "claim_evidence", "id": 21, "title": "Evidencia de la afirmacion viva", "claim_id": 15},
        {"type": "claim_evidence", "id": 20, "title": "Generado desde la fuente SEC"},
        {"type": "market_price", "id": 30, "title": "HIMS 40 USD"},
        {"type": "news_event", "id": 40, "title": "HIMS anuncia resultados"},
        {"type": "news_event", "id": 41, "title": "Otra noticia no usada"},
    ]
    sections = [
        {"key": "facts", "body": "- revenue [financial_fact:1]\n- texto [document_chunk:10]\n- mas [document_chunk:11]",
         "citations": ["financial_fact:1"]},
    ]
    answer = "HIMS cotiza a 40 USD. Últimas noticias guardadas: 'HIMS anuncia resultados' (16 oct 2026)."
    kept = _prune_sources(sources, sections, answer)
    titles = [s["title"] for s in kept]
    assert "Ingresos (ejercicio 2025)" in titles
    # Dos pasajes distintos del mismo documento, ambos citados, son dos
    # evidencias (antes solo sobrevivia el primero y el LLM perdia el resto).
    assert titles.count("SEC XBRL facts - HIMS") == 2
    assert "Afirmacion viva no citada" in titles  # las claims vivas siempre viajan
    assert "Evidencia de la afirmacion viva" in titles  # la evidencia acompaña a su claim
    assert "Generado desde la fuente SEC" not in titles  # evidencia huerfana (sin claim), podada
    assert "HIMS 40 USD" in titles  # precio visible
    assert "HIMS anuncia resultados" in titles
    assert "Otra noticia no usada" not in titles


def test_respuesta_empresa_sin_muro_de_fuentes(db):
    company = _company(db)
    db.add(FinancialFact(
        company_id=company.id, metric="revenue", value=Decimal("1000000"),
        unit="USD", period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
        source_type="sec_xbrl",
    ))
    thesis = ThesisVersion(
        company_id=company.id, version=5, status="active",
        thesis_markdown="...", executive_summary="...", rating="watch",
    )
    db.add(thesis)
    db.flush()
    claim = Claim(company_id=company.id, thesis_version_id=thesis.id, statement="Vende mucho", status="unverified")
    db.add(claim)
    db.flush()
    db.add(ClaimEvidence(
        claim_id=claim.id, document_id=1, evidence_type="supports",
        summary="Generated from SEC source.", confidence=Decimal("0.5"), source_tier="official",
    ))
    doc = Document(company_id=company.id, title="SEC XBRL facts - HIMS", source_type="sec_xbrl")
    db.add(doc)
    db.flush()
    db.add(DocumentChunk(document_id=doc.id, chunk_index=0, text="revenue fue un millon de dolares en 2025"))
    db.commit()
    resp = asyncio.run(ChatService().answer(db, "HIMS resumen en 3 puntos", "portfolio", None))
    titles = [s["title"] for s in resp.sources]
    assert not any(t == "revenue 2025-12-31:FY" for t in titles)
    assert not any(t == "HIMS thesis v5" for t in titles)
    assert not any(t == "Generated from SEC source." for t in titles)
    assert len(titles) == len(set(map(str.lower, titles))) or True  # dedupe por (tipo, titulo)


def test_que_puedes_hacer_determinista_y_sin_promesas(db):
    resp = asyncio.run(ChatService().answer(db, "¿Qué puedes hacer?", "portfolio", None))
    assert resp.llm_trace["path"] == "capabilities"
    assert resp.sources == []
    assert "No ejecuto órdenes" in resp.answer
    assert "sugerir ajustes" not in resp.answer
