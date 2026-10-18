"""FinancialTerminalService contracts: dedupe by source priority, window, honesty.

The terminal series feed the company UI: a restated fact must show once
(filing beats vendor; a empate, la ingesta mas reciente), the years window
must hold, periodicity filters must be exact, and missing metrics are
reported as missing - never fabricated with empty or zero series dressed
up as data.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import Base, CalculatedMetric, Company, FinancialFact
from app.services.financial_terminal_service import FinancialTerminalService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="AAA", name="AAA", exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fact(db, company, *, metric="revenue", period, fiscal_year, value, quarter=None, when=None):
    fact = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="USD", period=period, fiscal_year=fiscal_year, fiscal_quarter=quarter,
        source_type="seed", is_reported=True,
    )
    db.add(fact)
    db.flush()
    if when is not None:
        fact.created_at = when
        db.flush()
    db.commit()
    return fact


def _calculated(db, company, *, metric="roic", period, fiscal_year, value, status="ok"):
    row = CalculatedMetric(
        company_id=company.id, metric=metric,
        value=None if value is None else Decimal(str(value)),
        unit="decimal", period=period, fiscal_year=fiscal_year,
        status=status, formula="test", numerator=None, denominator=None,
    )
    db.add(row)
    db.commit()
    return row


def test_restated_fact_dedupes_latest_wins(db):
    company = _company(db)
    old = _fact(db, company, period="FY2024", fiscal_year=2024, value=100,
                when=datetime(2026, 1, 1, tzinfo=UTC))
    new = _fact(db, company, period="FY2024", fiscal_year=2024, value=110,
                when=datetime(2026, 2, 1, tzinfo=UTC))
    result = FinancialTerminalService().build(db, company, metrics=["revenue"])
    series = result["metrics"][0]["series"]
    assert len(series) == 1
    assert series[0]["id"] == new.id
    assert series[0]["value"] == new.value


def test_duplicate_period_filing_beats_vendor(db):
    """MSFT/V tenian dos «Deuda total» para el mismo FY: la del filing (SEC)
    y la refundicion del proveedor (FMP). Una sola fila y gana el filing,
    aunque el proveedor se ingeste despues."""
    company = _company(db)
    sec = _fact(db, company, metric="total_debt", period="2026-06-30:FY", fiscal_year=2026,
                value="31070000000", when=datetime(2026, 1, 1, tzinfo=UTC))
    sec.source_type = "SEC"
    fmp = _fact(db, company, metric="total_debt", period="2026-06-30:FY", fiscal_year=2026,
                value="40290000000", when=datetime(2026, 2, 1, tzinfo=UTC))
    fmp.source_type = "FMP"
    fmp.is_reported = False
    db.commit()
    result = FinancialTerminalService().build(db, company, metrics=["total_debt"])
    series = result["metrics"][0]["series"]
    assert len(series) == 1
    assert series[0]["id"] == sec.id
    assert series[0]["source"]["type"] == "SEC"


def test_duplicate_period_vendor_wins_when_no_filing(db):
    """Sin filing, la refundicion mas reciente del proveedor es la fila."""
    company = _company(db)
    old = _fact(db, company, metric="total_debt", period="2026-06-30:FY", fiscal_year=2026,
                value="100", when=datetime(2026, 1, 1, tzinfo=UTC))
    old.source_type = "FMP"
    new = _fact(db, company, metric="total_debt", period="2026-06-30:FY", fiscal_year=2026,
                value="110", when=datetime(2026, 2, 1, tzinfo=UTC))
    new.source_type = "FMP"
    new.is_reported = False
    db.commit()
    result = FinancialTerminalService().build(db, company, metrics=["total_debt"])
    series = result["metrics"][0]["series"]
    assert len(series) == 1
    assert series[0]["id"] == new.id
def test_fcf_missing_reason_points_at_capex(db):
    """Hallazgo 7: hay CFO pero no capex -> el FCF no se deriva ni se
    sustituye por cero; la tarjeta explica por que falta."""
    company = _company(db)
    _fact(db, company, metric="operating_cash_flow", period="FY2024", fiscal_year=2024, value=100)
    result = FinancialTerminalService().build(db, company, metrics=["free_cash_flow"])
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["missing_reason"] is not None
    assert "capex" in metric["missing_reason"]


def test_capex_missing_reason_for_banks(db):
    """JPM: los bancos no reportan capex desglosado en XBRL (companyfacts
    no tiene ningun tag de capex para JPM, verificado 2026-10-18)."""
    company = _company(db)
    company.industry = "Banks - Diversified"
    db.commit()
    result = FinancialTerminalService().build(db, company, metrics=["capital_expenditure"])
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert "bancos" in metric["missing_reason"].lower()


def test_missing_metric_without_known_reason_stays_generic(db):
    company = _company(db)
    result = FinancialTerminalService().build(db, company, metrics=["revenue"])
    assert result["metrics"][0]["missing_reason"] is None


def test_years_window_excludes_older_facts(db):
    company = _company(db)
    _fact(db, company, period="FY2020", fiscal_year=2020, value=1)
    _fact(db, company, period="FY2024", fiscal_year=2024, value=2)
    result = FinancialTerminalService().build(db, company, metrics=["revenue"], years=3)
    series = result["metrics"][0]["series"]
    assert [row["period"] for row in series] == ["FY2024"]
    assert result["range"] == {"from_fiscal_year": 2022, "to_fiscal_year": 2024}


def test_periodicity_filter_is_exact(db):
    company = _company(db)
    _fact(db, company, period="FY2024", fiscal_year=2024, value=10)
    _fact(db, company, period="Q1-2024", fiscal_year=2024, value=3, quarter="Q1")
    annual = FinancialTerminalService().build(
        db, company, metrics=["revenue"], periodicity="annual"
    )
    assert [row["period"] for row in annual["metrics"][0]["series"]] == ["FY2024"]
    quarterly = FinancialTerminalService().build(
        db, company, metrics=["revenue"], periodicity="quarterly"
    )
    assert [row["period"] for row in quarterly["metrics"][0]["series"]] == ["Q1-2024"]
    with pytest.raises(ValueError, match="periodicity"):
        FinancialTerminalService().build(db, company, metrics=["revenue"], periodicity="weekly")


def test_missing_metric_is_reported_never_fabricated(db):
    company = _company(db)
    _fact(db, company, period="FY2024", fiscal_year=2024, value=10)
    result = FinancialTerminalService().build(
        db, company, metrics=["revenue", "free_cash_flow"]
    )
    by_metric = {item["metric"]: item for item in result["metrics"]}
    assert by_metric["revenue"]["status"] == "available"
    assert by_metric["free_cash_flow"]["status"] == "missing"
    assert by_metric["free_cash_flow"]["series"] == []
    assert result["coverage"]["missing"] == ["free_cash_flow"]
    assert result["coverage"]["percent"] == 50.0

def test_calculated_without_inputs_is_missing_not_available(db):
    """Prod ASTS: ROIC figuraba «disponible / 1 periodo» y el cuerpo decia
    «Sin observaciones». La fila persistida por el calculo sin entradas
    (value=None, period "unknown") es trazabilidad, no una observacion:
    status y periods se derivan de observaciones validas."""
    company = _company(db)
    _calculated(db, company, metric="roic", period="unknown", fiscal_year=None, value=None, status="unavailable")
    result = FinancialTerminalService().build(db, company, metrics=["roic"])
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["periods"] == 0
    assert metric["series"] == []


def test_calculated_with_real_period_but_null_value_is_missing(db):
    """Owner earnings y margenes de ASTS: «disponible» con unico valor N/D.
    Una fila con periodo real pero valor nulo tampoco es una observacion."""
    company = _company(db)
    _calculated(db, company, metric="owner_earnings", period="FY2025", fiscal_year=2025, value=None, status="unavailable")
    result = FinancialTerminalService().build(db, company, metrics=["owner_earnings"])
    metric = result["metrics"][0]
    assert metric["status"] == "missing"
    assert metric["periods"] == 0
    assert metric["series"] == []


def test_valid_calculated_rows_still_count(db):
    """El filtro no se lleva observaciones reales: una calculada con valor
    y una de trazabilidad conviven; solo cuenta la valida."""
    company = _company(db)
    _calculated(db, company, metric="roic", period="FY2025", fiscal_year=2025, value="0.12")
    _calculated(db, company, metric="roic", period="unknown", fiscal_year=None, value=None, status="unavailable")
    result = FinancialTerminalService().build(db, company, metrics=["roic"])
    metric = result["metrics"][0]
    assert metric["status"] == "available"
    assert metric["periods"] == 1
    assert len(metric["series"]) == 1
