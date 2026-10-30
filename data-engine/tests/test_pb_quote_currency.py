"""P/B de la ficha con cierre en otra unidad/divisa que las cuentas.

Calculo independiente: TSCO.L-style, cuentas en GBP (equity 1000 GBP, 100
acciones -> 10 GBP/accion), cierre 250 GBp = 2,50 GBP -> P/B = 0,25.
En main se dividia 250 (peniques) entre 10 (libras): P/B 25, x100.
Cuentas en USD con cierre en GBp y sin tipo FX: N/D (nunca peniques/dolares).
"""

from decimal import Decimal

from app.models import MarketPrice
from tests import test_valuation_metrics as vm


def _quoted_price(db, company, close, quote_currency):
    db.add(MarketPrice(
        company_id=company.id, date=vm.AS_OF, close=Decimal(close),
        adj_close=Decimal(close), source="test", quote_currency=quote_currency,
    ))
    db.flush()


def _seed(db, ticker, currency, unit, close, quote):
    company = vm._company(ticker, currency=currency)
    db.add(company)
    db.flush()
    vm._fact(db, company, "total_equity", "1000", 2025, unit=unit)
    vm._fact(db, company, "shares_diluted", "100", 2025, unit=unit)
    _quoted_price(db, company, close, quote)
    return company


def test_pb_pence_close_against_pound_books():
    db = vm._db()
    company = _seed(db, "TSCO", "GBP", "GBP", "250", "GBp")
    vm._run(db, [company])
    row = vm._metric(db, company, vm.METRIC_PB)
    assert row is not None
    assert Decimal(row.value) == Decimal("0.25")
    assert row.calculation_trace["quote_currency"] == "GBp"


def test_pb_foreign_quote_without_fx_is_nd():
    db = vm._db()
    company = _seed(db, "SHEL", "USD", "USD", "2500", "GBp")
    stats = vm._run(db, [company])
    assert vm._metric(db, company, vm.METRIC_PB) is None
    assert stats["skipped"]["sin_fx_cotizacion"] == 1


def test_pb_same_currency_quote_unchanged():
    db = vm._db()
    company = _seed(db, "SAME", "USD", "USD", "20", "USD")
    vm._run(db, [company])
    assert Decimal(vm._metric(db, company, vm.METRIC_PB).value) == Decimal("2")
