"""Cross-check aditivo de multiplos relativos en ValuationService.value_company.

El contraste solo aparece cuando el motor resuelto es standard_dcf, viaja con
su procedencia (peer set, ids y periodos de los hechos) y nunca inventa una
cifra: sin peers va el estado y el motivo, no un valor.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.services.valuation_service import ValuationService

PERIOD = "FY2025"
FY = 2025
PRICE_DAY = date(2025, 12, 31)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker, *, company_type="standard", valuation_model="standard_dcf"):
    row = Company(
        ticker=ticker,
        name=f"{ticker} test",
        exchange="TEST",
        currency="USD",
        sector="Technology",
        industry="Software",
        company_type=company_type,
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=["software"],
    )
    db.add(row)
    db.flush()
    return row


def _facts(db, company, values, *, period=PERIOD, fiscal_year=FY, source_type="cross_check_test"):
    for metric, value in values.items():
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit="USD",
                period=period,
                fiscal_year=fiscal_year,
                fiscal_quarter="FY",
                source_type=source_type,
                is_reported=True,
                confidence=Decimal("0.90"),
            )
        )
    db.commit()


def _price(db, company, price, *, day=PRICE_DAY):
    db.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            close=Decimal(str(price)),
            adj_close=Decimal(str(price)),
            source="cross_check_test",
        )
    )
    db.commit()


def _peer(db, ticker, price, eps, *, revenue=1000.0, fcf=100.0, debt=200.0, cash=50.0, shares=100.0):
    peer = _company(db, ticker)
    _facts(
        db,
        peer,
        {
            "eps": eps,
            "revenue": revenue,
            "free_cash_flow": fcf,
            "total_debt": debt,
            "cash_and_equivalents": cash,
            "shares_diluted": shares,
            "book_value": 400.0,
        },
    )
    _price(db, peer, price)
    return peer


def _subject(db, ticker="SUBJ"):
    company = _company(db, ticker)
    _facts(
        db,
        company,
        {
            "eps": 2.0,
            "revenue": 1000.0,
            "free_cash_flow": 100.0,
            "fcf_margin": 0.1,
            "total_debt": 200.0,
            "cash_and_equivalents": 50.0,
            "shares_diluted": 100.0,
            "book_value": 400.0,
        },
    )
    _price(db, company, 20.0)
    return company


def test_cross_check_present_with_provenance_for_standard_dcf(db):
    subject = _subject(db)
    for i in range(6):
        _peer(db, f"PEER{i}", price=30.0 + i, eps=2.5 + i * 0.1)
    result = ValuationService().value_company(db, subject)
    cross = result.get("cross_checks", {}).get("relative_multiples")
    assert cross is not None
    assert cross["engine"] == "relative"
    assert cross["status"] == "ok"
    assert cross["base_value"] is not None and cross["base_value"] > 0
    assert cross["headline_multiple"]
    provenance = cross["provenance"]
    assert provenance["peer_set"]
    assert provenance["fact_ids"]
    assert provenance["periods"]


def test_cross_check_skipped_when_resolved_engine_is_not_standard_dcf(db):
    subject = _subject(db)
    subject.company_type = "reit"
    for i in range(6):
        _peer(db, f"PEER{i}", price=30.0 + i, eps=2.5 + i * 0.1)
    result = ValuationService().value_company(db, subject)
    assert "relative_multiples" not in result.get("cross_checks", {})


def test_cross_check_publishes_status_never_an_invented_figure_without_peers(db):
    subject = _subject(db)
    result = ValuationService().value_company(db, subject)
    cross = result.get("cross_checks", {}).get("relative_multiples")
    assert cross is not None
    assert cross["status"] == "insufficient_data"
    assert cross["base_value"] is None
    assert cross["missing_inputs"]


def test_cross_check_failure_never_breaks_the_main_valuation(db, monkeypatch):
    subject = _subject(db)
    for i in range(6):
        _peer(db, f"PEER{i}", price=30.0 + i, eps=2.5 + i * 0.1)

    def _boom(self, context):
        raise RuntimeError("fallo forzado del contraste")

    monkeypatch.setattr(
        "app.valuation.engines.relative_multiples.RelativeMultiplesEngine.value", _boom
    )
    result = ValuationService().value_company(db, subject)
    assert result is not None
    assert "relative_multiples" not in result.get("cross_checks", {})
