"""TTM desde la base de datos y derivación YTD en la ingesta SEC (AAPL).

Mismas cifras reales que tests/test_ttm_fundamentals.py (fixture
tests/fixtures/aapl_ttm.json). Sin red: el companyfacts es un dict mínimo con
el formato real de la SEC.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.ttm_service import build_company_ttm

M = 1_000_000


class _Fixture:
    """Cifras reales de Apple: tests/fixtures/aapl_ttm.json (ver «_fuente»)."""

    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)


aapl = _Fixture(json.loads((Path(__file__).parent / "fixtures" / "aapl_ttm.json").read_text("utf-8")))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker="AAPL"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="quality",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, metric, period, value, quarter, *, source="SEC", reported=True,
          unit="USD", source_id=None):
    db.add(FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
        period=period, fiscal_year=int(period[:4]) if quarter == "FY" else None,
        fiscal_quarter=quarter, source_type=source, is_reported=reported,
        source_id=source_id,
    ))


def _seed_revenue(db, company):
    # Trimestres de 3 meses (10-Q) y FY25 (10-K) de Apple, en millones.
    labels = ["Q1", "Q2", "Q3", "Q1", "Q2", "Q3"]
    for (_, end, val), label in zip(aapl.REVENUE_Q, labels, strict=True):
        _fact(db, company, "revenue", f"{end}:{label}", val, label)
    for _, end, val in aapl.REVENUE_FY:
        _fact(db, company, "revenue", f"{end}:FY", val, "FY")


def _metric(payload, name):
    return next(m for m in payload["metrics"] if m["metric"] == name)


def test_endpoint_ttm_ventas_y_balance_aapl(db):
    """Ventas TTM = 102.466 (Q4 FY25 = FY − 9M) + 143.756 + 111.184 + 109.417
    = 466.823; caja = último trimestre (27/06/2026) = 39.544."""
    company = _company(db)
    _seed_revenue(db, company)
    for (end, val), label in zip(aapl.CASH_Q, ["Q1", "Q2", "Q3", "Q1", "Q2", "Q3"], strict=True):
        _fact(db, company, "cash_and_equivalents", f"{end}:{label}", val, label)
    _fact(db, company, "cash_and_equivalents", f"{aapl.FY25_END}:FY", 35_934, "FY")
    db.commit()

    payload = build_company_ttm(db, company)
    revenue = _metric(payload, "revenue")
    assert revenue["value"] == Decimal("466823")
    assert revenue["basis"] == "TTM"
    assert revenue["label"] == "TTM (últimos 4 trimestres)"
    assert revenue["provenance"] == "INFERIDO"
    assert [q["origin"] for q in revenue["quarters"]] == ["FY-9M", "10-Q", "10-Q", "10-Q"]
    cash = _metric(payload, "cash_and_equivalents")
    assert cash["value"] == Decimal("39544")
    assert cash["basis"] == "Q"
    assert payload["as_of"].isoformat() == aapl.Q3_FY26
    assert _metric(payload, "net_income")["basis"] == "SIN_DATOS"


def test_fuente_oficial_gana_a_fmp_en_el_mismo_periodo(db):
    """Mismo trimestre en SEC y en FMP: gana SEC (SOURCE_PRIORITY)."""
    company = _company(db)
    _seed_revenue(db, company)
    _fact(db, company, "revenue", f"{aapl.Q3_FY26}:Q3", 1, "Q3", source="FMP")
    db.commit()
    assert _metric(build_company_ttm(db, company), "revenue")["value"] == Decimal("466823")


def test_segmento_no_entra_en_el_consolidado(db):
    company = _company(db)
    _seed_revenue(db, company)
    doc = Document(
        company_id=company.id, source_type="SEC", title="Segmento",
        source_url="https://example.com/segmento", metadata_={"segment": "iphone"},
    )
    db.add(doc)
    db.flush()
    _fact(db, company, "revenue", f"{aapl.Q3_FY26}:Q3", 5, "Q3", source="SEC", source_id=doc.id)
    db.commit()
    assert _metric(build_company_ttm(db, company), "revenue")["value"] == Decimal("466823")


def test_solo_anual_cae_a_fy_etiquetado(db):
    company = _company(db)
    _fact(db, company, "revenue", f"{aapl.FY25_END}:FY", 416_161, "FY")
    db.commit()
    revenue = _metric(build_company_ttm(db, company), "revenue")
    assert revenue["basis"] == "FY"
    assert revenue["label"] == "FY (último ejercicio)"
    assert revenue["value"] == Decimal("416161")


def test_stale_asts_operating_income_not_current(db):
    company = _company(db, ticker="ASTS")
    _fact(db, company, "revenue", "2026-06-30:FY", 115300000, "FY")
    _fact(db, company, "operating_income", "2021-03-31:FY", -2370000, "FY")
    db.commit()
    payload = build_company_ttm(db, company)
    old = _metric(payload, "operating_income")
    assert old["value"] is None
    assert old["basis"] == "SIN_DATOS"
    assert "2021-03-31" in old["note"]
    assert "2026-06-30" in old["note"]
    assert _metric(payload, "revenue")["value"] == Decimal("115300000")


def test_recent_annual_fallback_remains_available(db):
    company = _company(db)
    _fact(db, company, "revenue", "2026-06-30:FY", 100, "FY")
    _fact(db, company, "operating_income", "2025-12-31:FY", 20, "FY")
    db.commit()
    assert _metric(build_company_ttm(db, company), "operating_income")["value"] == Decimal("20")


def _seed_capex_over_ocf(db, company):
    """Cuatro trimestres consecutivos con capex > flujo operativo (capex en
    negativo, salida de caja): OCF 12.000 M, capex -15.500 M por trimestre."""
    quarters = [("2025-03-31", "Q1"), ("2025-06-30", "Q2"), ("2025-09-30", "Q3"), ("2025-12-31", "Q4")]
    for end, label in quarters:
        _fact(db, company, "operating_cash_flow", f"{end}:{label}", 12_000 * M, label)
        _fact(db, company, "capital_expenditure", f"{end}:{label}", -15_500 * M, label)


def test_fcf_negativo_por_capex_va_con_nota_explicada(db):
    company = _company(db, "CAPX")
    _seed_capex_over_ocf(db, company)
    db.commit()
    payload = build_company_ttm(db, company)
    fcf = next(m for m in payload["metrics"] if m["metric"] == "free_cash_flow")
    assert Decimal(str(fcf["value"])) == Decimal(4 * -3_500 * M)  # TTM: 4 trimestres de -3.500 M
    assert fcf["note"] is not None
    assert "capex" in fcf["note"].lower()
    assert "supera" in fcf["note"]
    assert "flujo de caja operativo" in fcf["note"]


def test_fcf_positivo_sin_nota_de_capex(db):
    company = _company(db, "CAPY")
    quarters = [("2025-03-31", "Q1"), ("2025-06-30", "Q2"), ("2025-09-30", "Q3"), ("2025-12-31", "Q4")]
    for end, label in quarters:
        _fact(db, company, "operating_cash_flow", f"{end}:{label}", 20_000 * M, label)
        _fact(db, company, "capital_expenditure", f"{end}:{label}", -15_500 * M, label)
    db.commit()
    payload = build_company_ttm(db, company)
    fcf = next(m for m in payload["metrics"] if m["metric"] == "free_cash_flow")
    assert Decimal(str(fcf["value"])) == Decimal(4 * 4_500 * M)  # TTM: 4 trimestres de 4.500 M
    assert fcf["note"] is None


def test_ocf_negativo_nota_distinta_del_capex(db):
    company = _company(db, "CAPZ")
    quarters = [("2025-03-31", "Q1"), ("2025-06-30", "Q2"), ("2025-09-30", "Q3"), ("2025-12-31", "Q4")]
    for end, label in quarters:
        _fact(db, company, "operating_cash_flow", f"{end}:{label}", -2_000 * M, label)
        _fact(db, company, "capital_expenditure", f"{end}:{label}", -15_500 * M, label)
    db.commit()
    payload = build_company_ttm(db, company)
    fcf = next(m for m in payload["metrics"] if m["metric"] == "free_cash_flow")
    assert fcf["note"] is not None
    assert "ya es negativo" in fcf["note"]
