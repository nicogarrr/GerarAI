"""Motores sectoriales (banco, materias primas) con ADR.

El libro/NAV y las acciones vienen del filing en acciones ORDINARIAS y el
precio es el del ADR (N ordinarias). Antes el margen de seguridad se medía
contra el precio del ADR: error xN. Ahora, como standard_dcf/utilities:
precio por ordinaria = precio ADR / N, y sin ratio se rechaza.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FinancialFact
from app.valuation.engines.base import ValuationContext, margin_of_safety
from app.valuation.engines.commodity import CommodityCycleEngine
from app.valuation.engines.sector_specific import BankValuationEngine


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


def _db(company_type, model, facts, tags):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    company = Company(ticker="ADRX", name="ADR Co", exchange="NYSE", currency="USD",
                      company_type=company_type, valuation_model=model,
                      special_sources=[], special_risks=[], factor_tags=tags)
    s.add(company)
    s.flush()
    for metric, value in facts.items():
        s.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(str(value)),
                            unit="decimal" if abs(value) < 1 else "USD", period="FY2025",
                            fiscal_year=2025, fiscal_quarter="FY", source_type="SEC",
                            is_reported=True, confidence=Decimal("0.9")))
    s.commit()
    return s, company


BANK = {"tangible_book_value": 1000, "shares_diluted": 100, "roe": 0.14,
        "cost_of_equity": 0.10, "book_value_growth": 0.04}


def _bank(tags, price):
    db, company = _db("bank", "bank_residual_income", BANK, tags)
    snap = _Snap({"shares_diluted": 100.0})
    return BankValuationEngine().value(ValuationContext(
        db=db, company=company, snapshot=snap, current_price=price, engine_key="bank"))


def test_bank_adr_margin_uses_price_per_ordinary_share():
    plain = _bank([], 10.0)
    adr = _bank(["adr:4"], 40.0)  # 1 ADR = 4 ordinarias -> 10 por ordinaria
    # A mano: libro/acción 1000/100 = 10; P/B base (0,14-0,04)/(0,10-0,04) = 1,6667
    assert adr["base_value"] == pytest.approx(10 * 0.10 / 0.06)
    expected = adr["expected_value"]
    assert adr["margin_of_safety"] == pytest.approx((expected - 10.0) / expected)
    assert adr["margin_of_safety"] == pytest.approx(plain["margin_of_safety"])
    # Antes: (E - 40) / E, un margen muy negativo para un banco barato.
    assert adr["margin_of_safety"] != pytest.approx(margin_of_safety(expected, 40.0))
    assert adr["adr_ratio"] == 4
    assert adr["listed_share_values"]["expected"] == pytest.approx(expected * 4)
    assert adr["comparable_price_basis"] == "ordinary_share"
    assert plain["listed_share_values"] is None


def test_bank_adr_without_ratio_is_refused():
    r = _bank(["adr"], 40.0)
    assert r["status"] != "ok"
    assert r["missing_inputs"] == ["adr_ratio"]


COMMODITY = {"production_volume": 1000, "cash_cost_per_unit": 1000,
             "realized_commodity_price": 2000, "effective_tax_rate": 0.25,
             "commodity_earnings_multiple": 8}


def _commodity(tags, price):
    db, company = _db("commodity", "commodity", COMMODITY, tags)
    snap = _Snap({"shares_diluted": 100.0, "net_debt": 50_000.0})
    return CommodityCycleEngine().value(ValuationContext(
        db=db, company=company, snapshot=snap, current_price=price, engine_key="commodity"))


def test_commodity_adr_margin_uses_price_per_ordinary_share():
    r = _commodity(["adr:2"], 80_000.0)  # BHP-like: 1 ADR = 2 ordinarias
    # A mano: base (2000-1000)*1000*0,75*8 - 50.000 = 5.950.000 / 100 = 59.500
    assert r["base_value"] == pytest.approx(59_500.0)
    expected = r["expected_value"]
    assert r["margin_of_safety"] == pytest.approx((expected - 40_000.0) / expected)
    assert r["listed_share_values"]["base"] == pytest.approx(119_000.0)


def test_commodity_adr_without_ratio_is_refused():
    r = _commodity(["adr"], 80_000.0)
    assert r["status"] != "ok"
    assert r["missing_inputs"] == ["adr_ratio"]
