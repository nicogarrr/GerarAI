"""Bordes de ``app.services.universal_search_service``: filtro por compania.

Lo que demuestra (todo con filas sembradas en AMBAS companias, de modo que
quitar cualquiera de estos filtros cambia el resultado: mutante en rojo):
- Con ``ticker`` resuelto, el filtro ``company_id`` se aplica en
  document_chunk (466), decision (493), la tanda de modelos narrativos (529,
  con serializacion de thesis_section por titulo y cuerpo, 535),
  _metric_candidates (580) e investment cases (734): de cada corpus solo
  aparece la compania pedida, nunca la otra (ni su id ni sus marcadores).
- Un ``ticker`` que no existe devuelve el payload ``not_found`` exacto
  (124, 283).

SQLite real en memoria; sin red; ``include_vector=False``.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    DecisionJournalEntry,
    Document,
    DocumentChunk,
    FinancialFact,
    InvestmentCaseStudy,
    Tenant,
    ThesisSection,
    ThesisVersion,
)
from app.services.universal_search_service import UniversalSearchService


def _company(db, ticker, name):
    company = Company(
        ticker=ticker,
        name=name,
        exchange="TEST",
        currency="USD",
        sector="Industrials",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _seed_corpus(db, company, marcador):
    version = ThesisVersion(
        company_id=company.id,
        version=1,
        status="published",
        thesis_markdown=f"# Tesis {marcador}",
        executive_summary="resumen",
    )
    db.add(version)
    db.flush()
    db.add(
        ThesisSection(
            thesis_version_id=version.id,
            company_id=company.id,
            section_key="tesis",
            title=f"Capital allocation discipline {marcador}",
            body="Capital allocation discipline prioritized reinvestment.",
            status="published",
        )
    )
    filing = Document(
        company_id=company.id,
        title=f"filing {marcador}",
        source_type="sec_filing",
        source_url=f"https://www.sec.gov/{marcador}",
    )
    db.add(filing)
    db.flush()
    db.add(
        DocumentChunk(
            document_id=filing.id,
            chunk_index=0,
            text=f"Capital allocation discipline prioritized reinvestment. {marcador} marker",
        )
    )
    db.add(
        DecisionJournalEntry(
            company_id=company.id,
            decision="buy",
            rationale=f"Capital allocation discipline drives this. {marcador} marker",
        )
    )
    db.add(
        InvestmentCaseStudy(
            company_id=company.id,
            title=f"Case {marcador}",
            summary=f"Capital allocation discipline case. {marcador} marker",
            outcome="neutral",
            lessons=[],
            status="published",
        )
    )
    db.add(
        FinancialFact(
            company_id=company.id,
            metric=f"capital allocation discipline {marcador}",
            value=Decimal("1"),
            unit="x",
            period="FY2024",
            fiscal_year=2024,
        )
    )
    db.add(
        CalculatedMetric(
            company_id=company.id,
            metric=f"capital allocation discipline {marcador}",
            value=Decimal("2"),
            unit="x",
            period="FY2024",
            fiscal_year=2024,
            status="ok",
            definition_version="v1",
            formula="x",
            source_fact_ids=[],
            calculation_trace={},
            confidence=Decimal("0.7"),
        )
    )


def test_busqueda_con_ticker_filtra_por_compania():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="search-bordes", name="Search bordes")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        srch = _company(db, "SRCH", "Search Co")
        otra = _company(db, "OTRA", "Other Co")
        _seed_corpus(db, srch, "SRCH")
        _seed_corpus(db, otra, "OTRA")
        db.commit()
        srch_id = srch.id
        otra_id = otra.id

        response = UniversalSearchService().search(
            db, "capital allocation discipline", ticker="srch", include_vector=False
        )

    results = response["results"]
    por_tipo = {}
    for r in results:
        por_tipo.setdefault(r["entity_type"], []).append(r)
    for tipo in (
        "document_chunk",
        "decision",
        "thesis_section",
        "investment_case",
        "financial_fact",
        "calculated_metric",
    ):
        assert len(por_tipo[tipo]) == 1, tipo
        assert por_tipo[tipo][0]["company_id"] == srch_id, tipo
    assert por_tipo["thesis_section"][0]["title"] == "Capital allocation discipline SRCH"
    assert all(r["company_id"] != otra_id for r in results)
    assert all("OTRA marker" not in r["text"] for r in results)


def test_ticker_desconocido_devuelve_not_found_exacto():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(external_id="search-bordes", name="Search bordes")
        db.add(tenant)
        db.flush()
        db.info["tenant_id"] = tenant.id
        db.commit()
        response = UniversalSearchService().search(db, "cualquier cosa", ticker="NOPE", include_vector=False)
    assert response == {
        "query": "cualquier cosa",
        "status": "not_found",
        "retrieval": {"mode": "lexical_only", "vector_requested": False},
        "total": 0,
        "results": [],
    }
