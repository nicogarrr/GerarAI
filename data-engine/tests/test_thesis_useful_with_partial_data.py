"""Tesis util con datos parciales (HYMC 2026-10-21).

La SEC publica serie anual aunque el ultimo 10-K omita una linea (HYMC:
sin linea de ingresos tras FY2023). La auto-ingesta debe traer la serie
reciente, el snapshot no debe pedir como ausente un dato persistido pero
excluido por periodo, y la narrativa sin LLM es un compendio factual
rotulado, nunca un analisis inventado.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FinancialFact
from app.services.thesis_evidence_service import ThesisEvidenceService
from app.services.thesis_news_narrative import compendio_factual, sin_datos
from app.services.thesis_service import ThesisService
from app.valuation.financial_snapshot import FinancialSnapshotBuilder


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="HYMC", name="Hycroft", exchange="NASDAQ", currency="USD",
        sector="Basic Materials", industry="Gold", company_type="operating",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _annual(val, end, filed, form="10-K", start=None):
    entry = {"form": form, "val": val, "end": end, "filed": filed}
    if start:
        entry["start"] = start
    return entry


def _fy(val, year, filed):
    return _annual(val, f"{year}-12-31", filed, start=f"{year}-01-01")


# -- serie anual reciente -----------------------------------------------------

def test_extract_recent_annuals_returns_three_year_series():
    us_gaap = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {"USD": [
                _fy(110_734_000, 2021, "2022-03-01"),
                _fy(33_229_000, 2022, "2023-03-01"),
                _fy(0, 2023, "2024-03-14"),
                _annual(1, "2024-06-30", "2024-08-01", form="10-Q", start="2024-04-01"),
            ]}
        }
    }
    out = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    series = out["revenue"]
    assert [item["value"] for item in series] == [0, 33_229_000, 110_734_000]
    assert all(item["period"].endswith(":FY") for item in series)


def test_extract_recent_annuals_falls_back_to_quarter_when_no_annual():
    us_gaap = {
        "Revenues": {
            "units": {"USD": [
                _annual(30, "2026-06-27", "2026-08-01", form="10-Q", start="2026-03-29"),
            ]}
        }
    }
    out = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert len(out["revenue"]) == 1
    assert out["revenue"][0]["period"] == "2026-06-27:10-Q"


def test_extract_recent_annuals_never_sums_tags_same_period():
    us_gaap = {
        "Revenues": {"units": {"USD": [_fy(100, 2024, "2025-02-01")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {"USD": [_fy(95, 2024, "2025-02-01")]}
        },
    }
    out = ThesisEvidenceService()._extract_recent_annuals(us_gaap)
    assert [item["value"] for item in out["revenue"]] == [100]


def test_ingest_fundamentals_imports_multiple_periods_additively(db, monkeypatch):
    service = ThesisEvidenceService()
    monkeypatch.setattr(
        service,
        "_fetch_company_facts",
        lambda cik: {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": [
                            _fy(33_229_000, 2022, "2023-03-01"),
                            _fy(0, 2023, "2024-03-14"),
                        ]}
                    }
                }
            }
        },
    )
    company = _company(db)
    result = service._ingest_fundamentals(db, company, "1718405")
    assert result["status"] == "ok"
    periods = {
        f.period
        for f in db.scalars(
            select(FinancialFact).where(FinancialFact.company_id == company.id)
        )
    }
    assert {"2023-12-31:FY", "2022-12-31:FY"} <= periods
    # segunda pasada: aditivo, sin duplicar
    result2 = service._ingest_fundamentals(db, company, "1718405")
    assert result2["facts_imported"] == 0


# -- snapshot: presente-excluido no es "ausente" -------------------------------

def _fact(db, company, metric, value, period, year):
    fact = FinancialFact(
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="USD" if metric != "shares_diluted" else "shares",
        period=period, fiscal_year=year, fiscal_quarter="FY",
        source_type="SEC", is_reported=True, confidence=Decimal("0.95"),
    )
    db.add(fact)
    db.commit()
    return fact


def test_snapshot_excluded_present_still_blocks_but_is_explained(db):
    """Un required excluido por periodo SIGUE bloqueando (coherent=False):
    la coherencia interna no se negocia. La distincion es solo explicacion
    al usuario via excluded_present."""
    company = _company(db)
    _fact(db, company, "revenue", 0, "2023-12-31:FY", 2023)
    _fact(db, company, "shares_diluted", 43_260_501, "2025-12-31:FY", 2025)
    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert "shares_diluted" in snapshot.missing_inputs
    assert snapshot.coherent is False
    excluded = {item["metric"]: item for item in snapshot.excluded_present}
    assert excluded["shares_diluted"]["available_period"] == "2025-12-31:FY"
    assert excluded["shares_diluted"]["anchor_period"] == "2023-12-31:FY"
    assert "revenue" in snapshot.missing_inputs


def test_positive_revenue_with_excluded_shares_is_insufficient_not_crash(db):
    """Caso del auditor: revenue FY positivo + acciones solo de un FY
    incompatible -> insufficient_data sin AssertionError (el assert de
    shares del motor nunca se alcanza porque coherent=False)."""
    from app.valuation.engines.standard_dcf import StandardDCFEngine

    company = _company(db)
    _fact(db, company, "revenue", 33_229_000, "2023-12-31:FY", 2023)
    _fact(db, company, "operating_cash_flow", -41_448_000, "2023-12-31:FY", 2023)
    _fact(db, company, "capital_expenditure", 5_000_000, "2023-12-31:FY", 2023)
    _fact(db, company, "total_debt", 142_617_000, "2023-12-31:FY", 2023)
    _fact(db, company, "cash_and_equivalents", 106_210_000, "2023-12-31:FY", 2023)
    _fact(db, company, "shares_diluted", 43_260_501, "2025-12-31:FY", 2025)
    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert snapshot.coherent is False
    assert "shares_diluted" in snapshot.missing_inputs
    engine = StandardDCFEngine()
    context = engine.build_context(db, company, 17.13)
    result = engine.value(context)
    assert result["status"] == "insufficient_data"
    assert result["publishable"] is False
    assert "shares_diluted" in result["missing_inputs"]
    assert any(
        item["metric"] == "shares_diluted" for item in result["excluded_inputs"]
    )


def test_snapshot_three_year_history_resolves_shares_and_net_debt(db):
    company = _company(db)
    _fact(db, company, "revenue", 0, "2023-12-31:FY", 2023)
    _fact(db, company, "revenue", 33_229_000, "2022-12-31:FY", 2022)
    _fact(db, company, "shares_diluted", 21_113_516, "2023-12-31:FY", 2023)
    _fact(db, company, "shares_diluted", 43_260_501, "2025-12-31:FY", 2025)
    _fact(db, company, "total_debt", 142_617_000, "2023-12-31:FY", 2023)
    _fact(db, company, "cash_and_equivalents", 106_210_000, "2023-12-31:FY", 2023)
    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert snapshot.value("shares_diluted") == 21_113_516
    assert snapshot.value("net_debt") == pytest.approx(142_617_000 - 106_210_000)
    assert "shares_diluted" not in snapshot.missing_inputs
    assert "net_debt" not in snapshot.missing_inputs


def test_zero_revenue_anchor_is_explained_not_requested(db):
    """HYMC real: ingresos FY2023 = 0 persistidos. El 0 no alimenta el DCF
    (sigue bloqueando: revenue en missing_inputs), pero el dato EXISTE:
    pedirlo al usuario como ausente seria falso -> excluded_present con
    reason present_not_usable."""
    company = _company(db)
    _fact(db, company, "revenue", 0, "2023-12-31:FY", 2023)
    _fact(db, company, "shares_diluted", 43_260_501, "2025-12-31:FY", 2025)
    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert "revenue" in snapshot.missing_inputs  # gating intacto
    assert snapshot.coherent is False
    excluded = {item["metric"]: item for item in snapshot.excluded_present}
    assert excluded["revenue"]["reason"] == "present_not_usable"
    assert excluded["revenue"]["available_period"] == "2023-12-31:FY"


def test_net_debt_with_excluded_components_is_explained_not_requested(db):
    """net_debt solo se deriva de componentes del periodo ancla. Si deuda y
    efectivo existen pero estan excluidos por periodo, net_debt sigue
    bloqueando (missing) pero se explica como presente-excluido derivado,
    no se pide como dato ausente."""
    company = _company(db)
    _fact(db, company, "revenue", 0, "2023-12-31:FY", 2023)
    _fact(db, company, "shares_diluted", 43_260_501, "2025-12-31:FY", 2025)
    _fact(db, company, "total_debt", 0, "2025-12-31:FY", 2025)
    _fact(db, company, "cash_and_equivalents", 181_740_000, "2025-12-31:FY", 2025)
    snapshot = FinancialSnapshotBuilder().build(db, company)
    assert "net_debt" in snapshot.missing_inputs  # gating intacto
    assert snapshot.coherent is False
    excluded = {item["metric"]: item for item in snapshot.excluded_present}
    assert excluded["net_debt"]["reason"] == "components_excluded"
    assert excluded["net_debt"]["available_period"] == "2025-12-31:FY"


# -- compendio factual sin LLM -------------------------------------------------

def test_compendio_factual_lists_real_headlines_and_disclaims_analysis():
    items = [
        {
            "id": "n1", "source_headline": "HYMC 8-K filed 2026-10-13",
            "date": "2026-10-13T00:00:00+00:00", "date_source": "sec",
            "source": "SEC", "url": "https://www.sec.gov/Archives/edgar/data/1718405/x",
        }
    ]
    sections = compendio_factual(items, datetime(2026, 10, 21, tzinfo=UTC))
    text = "\n".join(parrafo for sec in sections for parrafo in sec["parrafos"])
    assert "HYMC 8-K filed 2026-10-13" in text
    assert "SEC" in text and "2026-10-13" in text
    assert "sin análisis" in text
    assert "sec.gov" in text


def test_compendio_factual_without_headlines_is_sin_datos():
    assert compendio_factual([], datetime(2026, 10, 21, tzinfo=UTC)) == sin_datos()


# -- hipotesis precisa ----------------------------------------------------------

def test_hypothesis_with_price_but_no_valuation_says_so():
    text = ThesisService()._hypothesis(
        _company_obj := type("C", (), {"name": "Hycroft", "ticker": "HYMC", "currency": "USD"})(),
        {
            "current_price": 17.13, "base_value": None, "margin_of_safety": None,
            "missing_inputs": ["revenue", "normalized_fcf_or_fcf_margin"],
        },
    )
    assert "precio de mercado" in text
    assert "no es calculable" in text
    assert "faltan datos de mercado" not in text
