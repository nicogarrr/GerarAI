"""Cierre guardado anterior a un split ya efectivo: la base del precio es
desconocida (vieja si no hubo refresco, ya ajustada si un refresco reescribio
la serie), asi que PER y P/B salen N/D en todas las superficies, como el
margen de seguridad y el DCF inverso de la valoracion (#3227).

Calculo independiente del error que se evita: equity 1000, 100 acciones FY,
split 10:1 efectivo ayer, ultimo cierre de hace 3 dias = 20.
- Si el cierre ya venia ajustado (20 post-split): P/B real = 20 / (1000/1000) = 20;
  main daba 20 / (1000/100) = 2 (10x bajo).
- Si venia sin ajustar: P/B 2 seria correcto. No se sabe cual: N/D.
"""

from datetime import timedelta
from decimal import Decimal

from app.models import CorporateAction
from app.services.screener_fundamentals import load_screener_ratios
from tests import test_screener_fundamentals as scr
from tests import test_valuation_metrics as vm
from tests.test_screener_fundamentals import db  # noqa: F401  (fixture)


def test_pb_ficha_nd_si_cierre_anterior_a_split_efectivo():
    db_ = vm._db()
    company = vm._seed_pb(db_, price="20", price_day=vm.AS_OF - timedelta(days=3))
    vm._split(db_, company, "10", vm.AS_OF - timedelta(days=1))
    vm._run(db_, [company])
    assert vm._metric(db_, company, vm.METRIC_PB) is None


def test_pb_ficha_con_cierre_posterior_al_split_si_se_calcula():
    db_ = vm._db()
    company = vm._seed_pb(db_, price="20", price_day=vm.AS_OF)
    vm._split(db_, company, "10", vm.AS_OF - timedelta(days=1))
    vm._run(db_, [company])
    row = vm._metric(db_, company, vm.METRIC_PB)
    assert row is not None
    assert Decimal(row.value) == Decimal("20")


def _screener_case(db, close_day):
    company = scr._company(db)
    scr._price(db, company, "180", day=close_day)
    scr._fact(db, company, "eps_diluted", "6", "USD/share")
    scr._fact(db, company, "total_equity", "50000000000", "USD")
    scr._fact(db, company, "shares_diluted", "15000000000", "shares")
    scr._fact(db, company, "net_income", "10000000000", "USD")
    db.add(CorporateAction(
        company_id=company.id, action_type="split", ratio=Decimal("4"),
        effective_date=scr.TODAY - timedelta(days=1), description="test split",
    ))
    db.flush()
    return load_screener_ratios(db, {"AAPL"}, today=scr.TODAY)["AAPL"]


def test_screener_pe_pb_nd_si_cierre_anterior_a_split_efectivo(db):  # noqa: F811
    result = _screener_case(db, scr.TODAY - timedelta(days=3))
    assert result["pe"] is None
    assert result["pb"] is None
    # ROE no depende del precio: se mantiene (10B / 50B = 20 %).
    assert result["roe"] == 20.0
    assert result["ratioProvenance"]["price"]["basis"] == "unknown_after_split"


def test_screener_cierre_posterior_al_split_ajusta(db):  # noqa: F811
    # 180 / (6 / 4) = 120 ; P/B = 180 / (50B / 60B) = 216
    result = _screener_case(db, scr.TODAY)
    assert result["pe"] == 120.0
    assert result["pb"] == 216.0


# Yield TTM: Yahoo da los dividendos ya ajustados al split. Calculo
# independiente: dividendo 0,10 post-split (1,00 pre-split) en la ventana,
# split 10:1 ayer, ultimo cierre de hace 3 dias = 200 (sin ajustar).
# yield real = 1,00 / 200 = 0,5 % (o 0,10 / 20); main daba 0,10 / 200 = 0,05 %
# si el cierre venia sin ajustar, o lo correcto si ya venia ajustado: N/D.
_YIELD_EVENTS = [{"date": (vm.AS_OF - timedelta(days=30)).isoformat(), "amount": "0.10"}]


def test_yield_nd_si_cierre_anterior_a_split_efectivo():
    db_ = vm._db()
    company = vm._seed_pb(db_, price="200", price_day=vm.AS_OF - timedelta(days=3))
    vm._split(db_, company, "10", vm.AS_OF - timedelta(days=1))
    stats = vm._run(db_, [company], events=_YIELD_EVENTS)
    assert vm._metric(db_, company, vm.METRIC_YIELD) is None
    assert stats["skipped"]["precio_anterior_a_split"] == 1


def test_yield_con_cierre_posterior_al_split_si_se_calcula():
    db_ = vm._db()
    company = vm._seed_pb(db_, price="20", price_day=vm.AS_OF)
    vm._split(db_, company, "10", vm.AS_OF - timedelta(days=1))
    vm._run(db_, [company], events=_YIELD_EVENTS)
    row = vm._metric(db_, company, vm.METRIC_YIELD)
    assert row is not None
    assert Decimal(row.value) == Decimal("0.005")
