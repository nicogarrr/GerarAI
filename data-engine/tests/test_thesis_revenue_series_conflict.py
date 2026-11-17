"""Una afirmacion de revenue que no concilia con otro hecho reportado del
MISMO periodo (>2x) no puede salir «respaldada»: avisa, no oculta.

Caso real (CPT FY2025, medido por el Piloto en prod): la tesis marcaba
«respaldada / 1 prueba: ingresos 12,97 MUSD» mientras la vista de finanzas
mostraba 1.573,5 MUSD para el mismo 2025-12-31:FY. El claim se queda con su
cifra y su fuente visibles, pero su estado pasa a «unverified» y la metadata
serie_conflicto guarda ambas cifras.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Claim, Company, Document, FinancialFact, ThesisVersion
from app.services.thesis_service import ThesisService


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.info["tenant_id"] = 1
        yield s
    eng.dispose()


def _company(db):
    c = Company(ticker="CPT", name="Camden", exchange="NYSE", currency="USD",
                company_type="reit", valuation_model="standard_dcf", factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _doc(db, c, url="https://www.sec.gov/10k"):
    d = Document(company_id=c.id, title="CPT 10-K", source_type="SEC", source_url=url)
    db.add(d)
    db.commit()
    return d


def _thesis(db, c):
    t = ThesisVersion(company_id=c.id, version=1, status="draft",
                      thesis_markdown="# t", executive_summary="r")
    db.add(t)
    db.commit()
    return t


def _revenue_fact(db, c, value, period="2025-12-31:FY", source_id=None):
    f = FinancialFact(company_id=c.id, metric="revenue", value=Decimal(str(value)), unit="USD",
                      period=period, fiscal_year=2025, fiscal_quarter="FY",
                      source_type="SEC", is_reported=True, source_id=source_id)
    db.add(f)
    db.commit()
    return f


def _payload(c, value, doc, period="2025-12-31:FY"):
    return {
        "claim_id": f"{c.ticker}:revenue:{period}",
        "subject": c.ticker,
        "predicate": "revenue",
        "object": float(value),
        "unit": "USD",
        "period": period,
        "claim": f"Ingresos FY2025 de {c.ticker}: {value} USD.",
        "source_id": doc.id,
        "source_type": "sec_filing",
        "source_document_id": doc.id,
        "confidence": 0.9,
        "material": True,
        "materiality": "high",
        "verification_state": "reported",
    }


def _claims(db):
    return db.scalars(select(Claim)).all()


def test_conflicto_de_serie_mayor_que_2x_no_sale_respaldada(db):
    c = _company(db)
    thesis = _thesis(db, c)
    doc = _doc(db, c)
    # El hecho de la ingesta completa (arrendador) para el mismo periodo.
    _revenue_fact(db, c, 1_573_500_000)
    ThesisService()._persist_claims(db, c, thesis, [_payload(c, 12_970_000, doc)])
    (claim,) = _claims(db)
    assert claim.status == "unverified"
    conflict = claim.metadata_["series_conflict"]
    assert conflict["claim_value"] == 12_970_000.0
    assert conflict["conflicting_value"] == 1_573_500_000.0
    assert conflict["ratio"] > 2
    assert "conflicto de serie" in conflict["warning"]


def test_divergencia_menor_que_2x_si_sale_respaldada(db):
    c = _company(db)
    thesis = _thesis(db, c)
    doc = _doc(db, c)
    _revenue_fact(db, c, 15_000_000)  # ratio 1,16 con 12,97 M: concilia
    ThesisService()._persist_claims(db, c, thesis, [_payload(c, 12_970_000, doc)])
    (claim,) = _claims(db)
    assert claim.status == "supported"
    assert "series_conflict" not in claim.metadata_


def test_misma_cifra_no_es_conflicto(db):
    """El propio hecho del claim (misma cifra) nunca se marca contra si mismo."""
    c = _company(db)
    thesis = _thesis(db, c)
    doc = _doc(db, c)
    _revenue_fact(db, c, 12_970_000, source_id=doc.id)
    ThesisService()._persist_claims(db, c, thesis, [_payload(c, 12_970_000, doc)])
    (claim,) = _claims(db)
    assert claim.status == "supported"
    assert "series_conflict" not in claim.metadata_


def test_conflicto_en_otro_periodo_no_afecta(db):
    c = _company(db)
    thesis = _thesis(db, c)
    doc = _doc(db, c)
    _revenue_fact(db, c, 1_573_500_000, period="2024-12-31:FY")  # otro ejercicio
    ThesisService()._persist_claims(db, c, thesis, [_payload(c, 12_970_000, doc)])
    (claim,) = _claims(db)
    assert claim.status == "supported"
    assert "series_conflict" not in claim.metadata_
