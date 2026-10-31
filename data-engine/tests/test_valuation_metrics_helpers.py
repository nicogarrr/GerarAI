"""Tests de helpers de app/services/valuation_metrics_service.py (P/B, dividendos).

Logica de dinero: ventana TTM de dividendos, desacuerdo relativo, unidad de
dividendo y el P/B fail-closed (divisa, ejercicio, signo). Red vetada en
tests: los fetchers por defecto deben saltar, nunca llamar fuera.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.valuation_metrics_service as vms
from app.models.entities import Base, Company, FinancialFact


def test_red_vetada_en_tests():
    with pytest.raises(RuntimeError, match="Red vetada"):
        vms._network_forbidden_in_tests()
    with pytest.raises(RuntimeError, match="Red vetada"):
        vms.default_dividend_fetcher("AAPL")


def test_dividend_unit_declarada_mezclada_y_fallback(monkeypatch):
    assert vms._dividend_unit([{"currency": "USD"}, {"currency": "USD"}], None) == "USD"
    assert vms._dividend_unit([{"currency": "USD"}, {"currency": "EUR"}], None) is None
    monkeypatch.setattr(vms, "listing_quote_unit", lambda ticker, ccy: ccy)
    company = Company(
        ticker="DIV", name="DIV Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    assert vms._dividend_unit([{"amount": "1"}], company) == "USD"


def test_ttm_dividend_per_share_ventana_y_saneado():
    as_of = date(2026, 3, 10)
    events = [
        {"date": "2026-03-10", "amount": "0.50"},   # incluido (borde superior)
        {"date": "2025-03-11", "amount": "0.25"},   # incluido
        {"date": "2025-03-10", "amount": "9.99"},   # fuera de ventana (365d)
        {"date": "2026-03-11", "amount": "5.00"},   # futuro: no conocible
        {"date": "2025-06-01", "amount": "-1.00"},  # negativo: descartado
        {"date": "2025-07-01", "amount": "NaN"},    # no finito: descartado
        {"date": "no-fecha", "amount": "1.00"},     # fecha invalida
        {"amount": "1.00"},                          # sin fecha
    ]
    total, used = vms.ttm_dividend_per_share(events, as_of)
    assert total == Decimal("0.75")
    assert [u["date"] for u in used] == ["2026-03-10", "2025-03-11"]


def test_rel_disagree():
    assert vms._rel_disagree(Decimal(0), Decimal(0)) == Decimal(0)
    assert vms._rel_disagree(Decimal(10), Decimal(5)) == Decimal("0.5")
    assert vms._rel_disagree(Decimal(5), Decimal(10)) == Decimal("0.5")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db: Session, currency: str = "USD", ticker: str = "PB") -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency=currency,
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _fact(db: Session, company: Company, metric: str, fy: int, value: str, unit: str = "USD"):
    db.add(FinancialFact(
        company_id=company.id, tenant_id=1, metric=metric, value=Decimal(value),
        unit=unit, period="FY", fiscal_year=fy, fiscal_quarter="FY",
    ))
    db.commit()


def test_book_value_per_share_mismo_fy(db):
    company = _company(db)
    _fact(db, company, "total_equity", 2024, "1000000")
    _fact(db, company, "shares_diluted", 2024, "100000")
    out = vms._book_value_per_share(db, company, date(2025, 6, 1))
    assert out is not None
    assert out["bvps"] == Decimal("10")
    assert out["fiscal_year"] == 2024


def test_book_value_per_share_fail_closed(db):
    company = _company(db)
    # ejercicios distintos: no se mezclan
    _fact(db, company, "total_equity", 2024, "1000000")
    _fact(db, company, "shares_diluted", 2023, "100000")
    assert vms._book_value_per_share(db, company, date(2025, 6, 1)) is None

    db2_company = _company(db, ticker="PB2")
    _fact(db, db2_company, "total_equity", 2024, "-5")
    _fact(db, db2_company, "shares_diluted", 2024, "100000")
    assert vms._book_value_per_share(db, db2_company, date(2025, 6, 1)) is None


def test_book_value_per_share_divisa_exacta_fail_closed(db):
    # GBP (libras) != GBp (peniques): un upper() inflaba el P/B x100
    company = _company(db, currency="GBp")
    _fact(db, company, "total_equity", 2024, "1000000", unit="GBP")
    _fact(db, company, "shares_diluted", 2024, "100000", unit="GBP")
    assert vms._book_value_per_share(db, company, date(2025, 6, 1)) is None

    company2 = _company(db, currency="GBP", ticker="PB3")
    _fact(db, company2, "total_equity", 2024, "1000000", unit="GBP")
    _fact(db, company2, "shares_diluted", 2024, "100000", unit="GBP")
    out = vms._book_value_per_share(db, company2, date(2025, 6, 1))
    assert out is not None and out["bvps"] == Decimal("10")
