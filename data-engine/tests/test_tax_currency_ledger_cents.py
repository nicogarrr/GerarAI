"""Libro de divisas: los importes del resumen se publican en céntimos.

Antes el servicio agregaba los Decimals del motor con ``float(sum(...))`` y
publicaba la precisión de cálculo entera («2.2327165») donde el resto del
informe publica céntimos (``_money``, ROUND_HALF_UP); la UI lo mostraba en
crudo. Estos tests fijan la conversión a céntimos en el total, en el
desglose por divisa y en el saldo sin convertir, con un caso de redondeo
HALF_UP exacto (x.xx5 -> hacia arriba).

Hermético: SQLite en memoria, conversiones en la tabla ``fx_conversions``
(como las importa el Flex de IBKR), sin red.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FxConversion, FXRate, Portfolio, Transaction
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        session.commit()
        yield session


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


def _fx(db: Session, rate_date: date, rate: str) -> None:
    db.add(FXRate(
        base_currency="EUR", quote_currency="USD",
        rate=Decimal(rate), rate_date=rate_date, source="test",
    ))
    db.commit()


def _tx(db, company, day, action, qty, price, currency="USD"):
    db.add(Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)),
        fees=Decimal("0"), currency=currency,
    ))
    db.commit()


def _fxc(db, day: date, disposed_ccy: str, disposed: str, acquired_ccy: str, acquired: str):
    db.add(FxConversion(
        trade_date=day,
        disposed_currency=disposed_ccy, disposed_amount=Decimal(disposed),
        acquired_currency=acquired_ccy, acquired_amount=Decimal(acquired),
    ))
    db.commit()


def _report(db):
    return TaxReportService().compute_report(
        db, 2025, include_filing=False, fx_opening_complete=True,
    )


def test_currency_ledger_summary_rounds_to_cents(db):
    """Ganancia de divisa con decimales largos: el resumen publica céntimos."""
    c = _company(db, "AAA")
    _fx(db, date(2025, 1, 5), "0.90")
    _fx(db, date(2025, 3, 1), "0.91")
    _fx(db, date(2025, 3, 2), "0.9155")
    # 1) Financiación: 936 EUR compran 1.040 USD (coste real 0,90 EUR/USD).
    _fxc(db, date(2025, 1, 4), "EUR", "936", "USD", "1040")
    # 2) Compra de acciones: consume 1.000 USD de ese lote (quedan 40).
    _tx(db, c, date(2025, 1, 5), "buy", 10, 100)
    # 3) Venta: nuevo lote de 1.234,50 USD valorado a 0,91 EUR/USD.
    _tx(db, c, date(2025, 3, 1), "sell", 10, 123.45)
    # 4) Conversión de 333,33 USD a EUR al BCE de su fecha (0,9155):
    #    consume FIFO 40 USD a 0,90 y 293,33 USD a 0,91.
    _fxc(db, date(2025, 3, 2), "USD", "333.33", "EUR", "305.16")

    summary = _report(db)["summary"]

    assert summary["currency_ledger_status"] == "computed"
    gain = summary["currency_ledger_gain_base"]
    assert gain is not None
    # Exactamente dos decimales (o menos): nunca la precisión de cálculo.
    assert gain == round(gain, 2)
    # Valor de control calculado a mano (Decimal, sin float):
    cost = Decimal("40") * Decimal("0.90") + Decimal("293.33") * Decimal("0.91")
    expected = Decimal("333.33") * Decimal("0.9155") - cost  # 2,2327165 EUR
    assert expected > Decimal("2.23") and gain == 2.23
    # Desglose por divisa y saldo sin convertir, también en céntimos.
    usd = summary["currency_ledger_by_currency"]["USD"]
    assert usd["gain_base"] == gain
    assert usd["unconverted"] == 941.17  # 40 + 1.234,50 - 333,33
    assert summary["currency_ledger_blocked_loss_base"] == 0.0


def test_currency_ledger_rounding_is_half_up(db):
    """Un x.xx5 exacto redondea hacia arriba (ROUND_HALF_UP), no bancario."""
    _fx(db, date(2025, 1, 4), "0.80")
    _fx(db, date(2025, 3, 2), "0.82125")
    # Lote de 1.000 USD a coste real 800 EUR; se convierten 100 USD.
    _fxc(db, date(2025, 1, 4), "EUR", "800", "USD", "1000")
    _fxc(db, date(2025, 3, 2), "USD", "100", "EUR", "82.12")

    summary = _report(db)["summary"]

    # Transmisión 100*0,82125 = 82,125 EUR; coste 80 EUR; ganancia exacta 2,125.
    assert summary["currency_ledger_gain_base"] == 2.13
    usd = summary["currency_ledger_by_currency"]["USD"]
    assert usd["gain_base"] == 2.13
    assert usd["unconverted"] == 900.0
