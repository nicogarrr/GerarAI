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


def _company(db, ticker, *, company_type="standard", valuation_model="standard_dcf",
             currency="USD", factor_tags=None):
    row = Company(
        ticker=ticker,
        name=f"{ticker} test",
        exchange="TEST",
        currency=currency,
        sector="Technology",
        industry="Software",
        company_type=company_type,
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=factor_tags if factor_tags is not None else ["software"],
    )
    db.add(row)
    db.flush()
    return row


def _facts(db, company, values, *, period=PERIOD, fiscal_year=FY, source_type="cross_check_test",
           unit="USD"):
    for metric, value in values.items():
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(str(value)),
                unit=unit,
                period=period,
                fiscal_year=fiscal_year,
                fiscal_quarter="FY",
                source_type=source_type,
                is_reported=True,
                confidence=Decimal("0.90"),
            )
        )
    db.commit()


def _price(db, company, price, *, day=PRICE_DAY, quote_currency="USD"):
    db.add(
        MarketPrice(
            company_id=company.id,
            date=day,
            close=Decimal(str(price)),
            adj_close=Decimal(str(price)),
            quote_currency=quote_currency,
            source="cross_check_test",
        )
    )
    db.commit()


def _peer(db, ticker, price, eps, *, revenue=1000.0, fcf=100.0, debt=200.0, cash=50.0, shares=100.0,
          currency="USD"):
    peer = _company(db, ticker, currency=currency)
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
        unit=currency,
    )
    _price(db, peer, price, quote_currency=currency)
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


# ---------------------------------------------------------- divisa cruzada / ADR

from app.models.entities import FXRate  # noqa: E402


def _fx(db, base, quote, rate, *, day=PRICE_DAY):
    # quote amount x rate = base amount (misma convencion que los tests FX)
    db.add(
        FXRate(
            base_currency=base,
            quote_currency=quote,
            rate=Decimal(str(rate)),
            rate_date=day,
            source="cross_check_fx_test",
        )
    )
    db.commit()


def _subject_ccy(db, ticker, currency, price, *, factor_tags=None):
    company = _company(db, ticker, currency=currency, factor_tags=factor_tags)
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
        unit=currency,
    )
    _price(db, company, price, quote_currency=currency if factor_tags is None else "USD")
    return company


def _direct_relative_base(db, company, price_reporting):
    """Base cruda del motor relativo: por accion ordinaria, divisa de cuentas."""
    from app.valuation.engines.relative_multiples import RelativeMultiplesEngine

    engine = RelativeMultiplesEngine()
    context = engine.build_context(db, company, price_reporting, None)
    return engine.value(context)


def test_cross_check_eur_subject_with_usd_peers_is_not_rescaled(db):
    subject = _subject_ccy(db, "SAN.MC", "EUR", 3.5)
    for i in range(6):
        _peer(db, f"USP{i}", price=30.0 + i, eps=2.5 + i * 0.1)
    result = ValuationService().value_company(db, subject)
    cross = result.get("cross_checks", {}).get("relative_multiples")
    assert cross is not None and cross["status"] == "ok"
    assert cross["value_currency"] == "EUR"
    assert cross["engine_value_currency"] == "EUR"
    assert cross["scale_factor_to_listing"] == 1.0
    raw = _direct_relative_base(db, subject, 3.5)
    # Misma divisa en todo el camino: la cifra es EXACTAMENTE la del motor,
    # sin reescalado (ni una ni dos veces).
    assert cross["base_value"] == pytest.approx(raw["base_value"], rel=1e-9)


def test_cross_check_usd_subject_with_eur_peers_keeps_usd(db):
    subject = _subject_ccy(db, "SUBJUS", "USD", 20.0)
    for i in range(6):
        _peer(db, f"EURP{i}", price=30.0 + i, eps=2.5 + i * 0.1, currency="EUR")
    result = ValuationService().value_company(db, subject)
    cross = result.get("cross_checks", {}).get("relative_multiples")
    assert cross is not None and cross["status"] == "ok"
    assert cross["value_currency"] == "USD"
    assert cross["engine_value_currency"] == "USD"
    assert cross["scale_factor_to_listing"] == 1.0
    raw = _direct_relative_base(db, subject, 20.0)
    assert cross["base_value"] == pytest.approx(raw["base_value"], rel=1e-9)


def test_cross_check_adr_scales_once_and_publishes_listed_values(db):
    # BABA-like: cuentas en CNY, listado USD como ADR 8:1, FX 1 USD = 7,1 CNY.
    # (Compania con currency de LISTADO USD y hechos en CNY, como en prod.)
    subject = _company(db, "BABA", currency="USD", factor_tags=["adr:8", "software"])
    _facts(
        db,
        subject,
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
        unit="CNY",
    )
    _price(db, subject, 80.0, quote_currency="USD")
    _fx(db, "CNY", "USD", "7.1")  # rate_date = dia del precio: la puerta FX evalua frescura contra esa fecha
    for i in range(6):
        _peer(db, f"CNP{i}", price=30.0 + i, eps=2.5 + i * 0.1)
    result = ValuationService().value_company(db, subject)
    cross = result.get("cross_checks", {}).get("relative_multiples")
    assert cross is not None and cross["status"] == "ok"
    assert cross["engine_value_currency"] == "CNY"
    assert cross["value_currency"] == "USD"
    assert cross["adr_ratio"] == 8.0
    assert cross["value_per_share_basis"] == "ordinary_share"
    raw = _direct_relative_base(db, subject, 80.0 * 7.1)
    # Un unico reescalado CNY -> USD: base = bruta / 7,1 (no / 7,1 dos veces).
    assert cross["base_value"] == pytest.approx(raw["base_value"] / 7.1, rel=1e-6)
    assert cross["base_value"] != pytest.approx(raw["base_value"] / (7.1**2), rel=1e-3)
    # La base comparable con el precio del ADR va por unidad listada:
    assert cross["listed_share_values"]["base"] == pytest.approx(cross["base_value"] * 8.0, rel=1e-6)
