"""Rentabilidad por dividendo con cierre y dividendos en unidades distintas.

Yahoo da los dividendos en la unidad de SU cotizacion (TSCO.L: peniques,
comprobado: cierre 537.88 GBp, dividendo 9.7 GBp). El cierre guardado puede
venir de otra fuente con otra unidad o sin unidad declarada.

Calculo independiente: dividendos 15 GBp en 12 meses, cierre guardado
5.00 GBP (= 500 GBp) -> yield = 15 / 500 = 0.03 (3 %). Main dividia 15 / 5.00
= 3 (300 %): 100 veces inflado. Un cierre sin unidad en un listado de
Londres no establece su unidad -> N/D, como el P/B (#3261).
"""
from datetime import timedelta
from decimal import Decimal

from tests import test_valuation_metrics as vm

_EVENTS_GBP_PENCE = [
    {"date": (vm.AS_OF - timedelta(days=100)).isoformat(), "amount": "10", "currency": "GBp"},
    {"date": (vm.AS_OF - timedelta(days=200)).isoformat(), "amount": "5", "currency": "GBp"},
]


def _london(db, close, unit):
    company = vm._seed_pb(db, ticker="TSCO.L", currency="GBP", unit="GBP", price=close)
    row = db.scalar(vm.select(vm.MarketPrice).where(vm.MarketPrice.company_id == company.id))
    row.quote_currency = unit
    db.flush()
    return company


def test_yield_cierre_en_libras_con_dividendos_en_peniques():
    db = vm._db()
    company = _london(db, "5.00", "GBP")
    vm._run(db, [company], events=_EVENTS_GBP_PENCE)
    row = vm._metric(db, company, vm.METRIC_YIELD)
    assert row is not None
    assert Decimal(row.value) == Decimal("0.03")
    assert row.calculation_trace["dividend_currency"] == "GBp"


def test_yield_cierre_en_peniques_sin_cambio():
    db = vm._db()
    company = _london(db, "500", "GBp")
    vm._run(db, [company], events=_EVENTS_GBP_PENCE)
    assert Decimal(vm._metric(db, company, vm.METRIC_YIELD).value) == Decimal("0.03")


def test_yield_nd_si_el_cierre_de_londres_no_declara_unidad():
    db = vm._db()
    company = _london(db, "500", None)
    legacy = [{k: v for k, v in e.items() if k != "currency"} for e in _EVENTS_GBP_PENCE]
    stats = vm._run(db, [company], events=legacy)
    assert vm._metric(db, company, vm.METRIC_YIELD) is None
    assert stats["skipped"]["sin_unidad_cotizacion"] == 1


def test_yield_nd_si_cierre_y_dividendos_son_de_otra_divisa():
    db = vm._db()
    company = _london(db, "6.50", "USD")
    stats = vm._run(db, [company], events=_EVENTS_GBP_PENCE)
    assert vm._metric(db, company, vm.METRIC_YIELD) is None
    assert stats["skipped"]["sin_unidad_cotizacion"] == 1
