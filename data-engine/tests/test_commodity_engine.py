"""Motor de valoración de materias primas: honestidad ante datos incompletos,
periodos incoherentes, supuestos inválidos y trazabilidad de hechos.

Run from data-engine/:
    pytest tests/test_commodity_engine.py -v
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FinancialFact
from app.valuation.engines.base import ValuationContext
from app.valuation.engines.commodity import CommodityCycleEngine


class _Snap:
    excluded_present: list = []
    coherent = False
    as_of_period = None
    income_statement = None
    balance_sheet = None
    shares_period = None
    warnings: list = []
    facts: dict = {}
    missing_inputs: list = []

    def __init__(self, values):
        self._v = values

    def value(self, metric):
        return self._v.get(metric)

    def fact_ids(self):
        return {}

    def periods(self):
        return {}


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Company(ticker="GOLD", name="Gold Co", exchange="NYSE", currency="USD",
                      company_type="commodity", valuation_model="commodity",
                      special_sources=[], special_risks=[], factor_tags=[]))
        s.commit()
        yield s


def _facts(db, **over):
    cid = db.query(Company).one().id
    base = {
        "production_volume": ("1000", 2024),
        "cash_cost_per_unit": ("1000", 2024),
        "realized_commodity_price": ("2000", 2024),
        "effective_tax_rate": ("0.25", 2024),
        "commodity_earnings_multiple": ("8", 2024),
    }
    base.update(over)
    ids = {}
    for metric, spec in base.items():
        if spec is None:
            continue
        value, year = spec
        f = FinancialFact(company_id=cid, metric=metric, value=Decimal(value), period=f"FY{year}",
                          fiscal_year=year, confidence=Decimal("0.9"))
        db.add(f)
        db.flush()
        ids[metric] = f.id
    db.commit()
    return ids


def _run(db, shares=100.0, net_debt=50_000.0, price=40.0):
    company = db.query(Company).one()
    snap = _Snap({"shares_diluted": shares, "net_debt": net_debt})
    return CommodityCycleEngine().value(
        ValuationContext(db=db, company=company, snapshot=snap, current_price=price, engine_key="commodity")
    )


def test_happy_path_values_and_ordering(db):
    ids = _facts(db)
    r = _run(db)
    assert r["status"] == "ok" and r["publishable"] is True
    # base: (2000-1000)*1000*(1-.25)=750k; *8=6.0M; -50k net debt => 5.95M / 100 sh = 59,500
    assert r["base_value"] == pytest.approx(59_500.0)
    assert r["bear_value"] < r["base_value"] < r["bull_value"]
    # grid bear: price 1500 -> (500*1000*.75*8 - 50k)/100 = 29,500
    assert r["bear_value"] == pytest.approx(29_500.0)
    assert r["trace"]["fact_ids"]["production_volume"] == ids["production_volume"]
    assert r["trace"]["commodity_input_metrics"]["price"] == "realized_commodity_price"
    assert r["margin_of_safety"] is not None


def test_alias_metric_is_labelled_with_its_real_name(db):
    ids = _facts(db, production_volume=None, sales_volume=("1000", 2024))
    r = _run(db)
    assert r["status"] == "ok"
    assert "production_volume" not in r["trace"]["fact_ids"]
    assert r["trace"]["fact_ids"]["sales_volume"] is not None


def test_price_below_cost_floors_flow_at_zero_never_negative(db):
    _facts(db, realized_commodity_price=("500", 2024))
    r = _run(db, net_debt=0.0)
    assert r["status"] == "ok"
    assert r["base_value"] == pytest.approx(0.0)
    assert r["bear_value"] == pytest.approx(0.0)


def test_missing_net_debt_is_not_treated_as_zero(db):
    _facts(db)
    r = _run(db, net_debt=None)
    assert r["status"] == "insufficient_data" and "net_debt" in r["missing_inputs"]
    assert r["base_value"] is None and r["publishable"] is False


def test_all_missing_inputs_listed(db):
    r = _run(db, shares=None, net_debt=None)
    assert r["status"] == "insufficient_data"
    assert {"production_volume_or_sales_volume", "cash_cost_per_unit", "realized_or_spot_commodity_price",
            "effective_tax_rate", "commodity_earnings_multiple", "shares_diluted", "net_debt"} <= set(r["missing_inputs"])


def test_zero_or_negative_shares_is_missing(db):
    _facts(db)
    assert "shares_diluted" in _run(db, shares=0.0)["missing_inputs"]


def test_mixed_periods_between_volume_cost_and_realized_price_blocks(db):
    _facts(db, cash_cost_per_unit=("1000", 2023))
    r = _run(db)
    assert r["status"] == "insufficient_data"
    assert r["missing_inputs"] == ["consistent_period_volume_cost_price"]


def test_spot_price_may_come_from_another_period(db):
    _facts(db, realized_commodity_price=None, spot_commodity_price=("2000", 2025))
    assert _run(db)["status"] == "ok"


@pytest.mark.parametrize("tax,mult", [("1", "8"), ("-0.1", "8"), ("0.25", "0"), ("0.25", "-3")])
def test_invalid_tax_or_multiple_blocks(db, tax, mult):
    _facts(db, effective_tax_rate=(tax, 2024), commodity_earnings_multiple=(mult, 2024))
    r = _run(db)
    assert r["status"] == "insufficient_data"
    assert r["missing_inputs"] == ["valid_effective_tax_rate_and_commodity_earnings_multiple"]
