"""Informe fiscal español (IRPF): dividendo EEUU, compensación y límites.

Cubre con el comportamiento real del fuente (TaxReportService):
- retención 15% EEUU convertida con el FX de la fecha de pago;
- compensación de ganancias y pérdidas dentro del mismo ejercicio;
- sin arrastre automático: pérdidas de ejercicios anteriores no reducen
  el neto del año en curso (límite documentado, no verde falso);
- umbral Modelo 720: implementado en Modelo720Service (ver el test);
- scrip cash-vs-acciones: el fuente no lo implementa → skip explícito con motivo.

Hermético: SQLite en memoria, sin red.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _eur_portfolio(db: Session) -> None:
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.commit()


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fx(db: Session, pair_base: str, pair_quote: str, rate_date: date, rate: str) -> None:
    db.add(FXRate(
        base_currency=pair_base, quote_currency=pair_quote,
        rate=Decimal(rate), rate_date=rate_date, source="test",
    ))
    db.commit()


def _tx(db, company, day, action, qty, price, currency="USD", fees="0"):
    db.add(Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)),
        fees=Decimal(str(fees)), currency=currency,
    ))
    db.commit()


def test_us_withholding_15pct_converted_at_payment_date_fx(db):
    _eur_portfolio(db)
    c = _company(db, "AAPL")
    pay_day = date(2026, 5, 15)
    # FX anterior distinto: debe usarse el de la fecha de pago.
    _fx(db, "EUR", "USD", date(2026, 1, 2), "0.80")
    _fx(db, "EUR", "USD", pay_day, "0.90")
    _tx(db, c, pay_day, "dividend", 0, 100)      # bruto 100 USD
    _tx(db, c, pay_day, "withholding", 0, 15)    # retención 15 USD (15%)

    report = TaxReportService().compute_report(db, 2026)
    row = next(r for r in report["dividends"] if r["ticker"] == "AAPL")
    assert row["dividends_native"] == 100.0
    assert row["withholding_native"] == 15.0
    assert row["dividends_base"] == pytest.approx(90.0)     # 100 × 0.90
    assert row["withholding_base"] == pytest.approx(13.5)   # 15 × 0.90
    assert row["missing_fx"] is False
    assert report["summary"]["total_withholding_base"] == pytest.approx(13.5)
    assert report["summary"]["incomplete_fx"] is False


def test_same_year_gains_and_losses_net_out(db):
    _eur_portfolio(db)
    win = _company(db, "WIN")
    lose = _company(db, "LOSE")
    _tx(db, win, date(2026, 1, 10), "buy", 10, 100, currency="EUR")
    _tx(db, win, date(2026, 6, 1), "sell", 10, 150, currency="EUR")    # +500
    _tx(db, lose, date(2026, 2, 10), "buy", 10, 100, currency="EUR")
    _tx(db, lose, date(2026, 9, 1), "sell", 10, 60, currency="EUR",
        fees="0")  # −400; sin recompra → computable
    # Sin recompra en ±2 meses la pérdida es computable (wash-sale no aplica).

    report = TaxReportService().compute_report(db, 2026)
    assert report["summary"]["total_realized_gain_base"] == pytest.approx(100.0)
    assert report["summary"]["net_taxable_base"] == pytest.approx(100.0)


def test_no_automatic_carryforward_prior_year_loss_excluded(db):
    """El SUMARIO es por ejercicio: la pérdida de 2025 no minora el neto de
    2026. El arrastre (art. 49 LIRPF) vive en la capa `filing`
    (loss_compensation, ver test_tax_irpf_filing.py), no en el sumario."""
    _eur_portfolio(db)
    c = _company(db, "OLD")
    _tx(db, c, date(2025, 2, 10), "buy", 10, 100, currency="EUR")
    _tx(db, c, date(2025, 6, 1), "sell", 10, 60, currency="EUR")   # −400 en 2025
    _tx(db, c, date(2026, 1, 10), "buy", 10, 100, currency="EUR")
    _tx(db, c, date(2026, 6, 1), "sell", 10, 150, currency="EUR")  # +500 en 2026

    report = TaxReportService().compute_report(db, 2026)
    assert report["summary"]["total_realized_gain_base"] == pytest.approx(500.0)
    assert report["summary"]["net_taxable_base"] == pytest.approx(500.0)


def test_modelo_720_threshold_lives_in_modelo720_service_and_is_strict():
    """El umbral SÍ está implementado, pero en Modelo720Service (no en
    TaxReportService, que es el IRPF): 50.000 € por categoría, y la obligación
    nace al EXCEDERLO (50.000,00 no obliga, 50.000,01 sí)."""
    from datetime import date as _date

    from app.services.tax_modelo720_service import THRESHOLD_720, Modelo720Service
    from tests.test_tax_modelo720_service import _company, _position_row, _position_snapshot, _seed

    assert THRESHOLD_720 == Decimal("50000")
    results = {}
    for amount in ("50000", "50000.01"):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            tenant, portfolio = _seed(session, custody={"US0378331005": "IE"})
            c = _company(session, tenant, "AAPL", isin="US0378331005")
            _position_row(session, tenant, portfolio, c)
            _position_snapshot(session, tenant, portfolio, c, _date(2025, 12, 31), Decimal(amount))
            results[amount] = Modelo720Service().check_thresholds(session, 2025)["categories"]["valores"]
    assert results["50000"]["exceeds"] is False and results["50000"]["status"] == "por_debajo"
    assert results["50000.01"]["exceeds"] is True and results["50000.01"]["status"] == "supera"


def test_scrip_rows_are_not_counted_as_cash_dividends_and_are_flagged_for_review(db):
    """Scrip (efectivo vs acciones): el criterio fiscal NO está implementado.
    Fail-closed: la fila no suma a dividendos ni a la casilla 0029 y se marca
    para revisión manual, en vez de tratarse como dividendo en efectivo."""
    _eur_portfolio(db)
    c = _company(db, "SAN")
    pay = date(2026, 5, 15)
    _fx(db, "EUR", "USD", pay, "0.90")
    _tx(db, c, pay, "dividend", 0, 100)                      # dividendo ordinario 100 USD
    db.add(Transaction(
        company_id=c.id, trade_date=pay, action="dividend", quantity=Decimal("0"), price=Decimal("200"),
        fees=Decimal("0"), currency="USD", raw_payload={"type": "Scrip Dividend"},
    ))
    db.commit()

    report = TaxReportService().compute_report(db, 2026)
    bucket = next(b for b in report["dividends"] if b["ticker"] == "SAN")
    # Solo el ordinario: 100 USD * 0,90 = 90 EUR (el scrip de 200 no suma).
    assert bucket["dividends_base"] == pytest.approx(90.0)
    assert len(bucket["special_payments"]) == 1
    assert bucket["special_payments"][0]["raw_action"] == "Scrip Dividend"
    assert bucket["special_payments"][0]["type"] == "special"
