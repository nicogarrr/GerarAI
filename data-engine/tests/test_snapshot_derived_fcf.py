"""FCF derivado de OCF y capex del mismo periodo cuando no hay FCF ni margen."""

from __future__ import annotations

from decimal import Decimal

from app.models.entities import FinancialFact
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from tests.test_snapshot_derived_net_debt import _company, db  # noqa: F401

P = "2025-12-31:FY"


def _f(db, c, metric, value, unit="USD"):
    f = FinancialFact(company_id=c.id, metric=metric, value=Decimal(str(value)), unit=unit,
                      period=P, fiscal_year=2025, fiscal_quarter="FY", source_type="SEC")
    db.add(f)
    db.commit()
    return f


def test_fcf_and_margin_derived_from_ocf_and_negative_capex(db):
    c = _company(db)
    _f(db, c, "revenue", 1000)
    ocf = _f(db, c, "operating_cash_flow", 300)
    capex = _f(db, c, "capital_expenditure", -100)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("free_cash_flow") == 200.0
    assert snap.value("fcf_margin") == 0.2
    assert snap.derived["free_cash_flow"] == [ocf.id, capex.id]
    assert snap.facts["free_cash_flow"].source_type == "DERIVED"
    assert "normalized_fcf_or_fcf_margin" not in snap.missing_inputs


def test_positive_capex_is_still_an_outflow(db):
    c = _company(db)
    _f(db, c, "revenue", 1000)
    _f(db, c, "operating_cash_flow", 300)
    _f(db, c, "capital_expenditure", 100)
    assert FinancialSnapshotBuilder().build(db, c).value("free_cash_flow") == 200.0


def test_negative_fcf_is_kept_negative(db):
    c = _company(db)
    _f(db, c, "revenue", 1000)
    _f(db, c, "operating_cash_flow", 50)
    _f(db, c, "capital_expenditure", -150)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("free_cash_flow") == -100.0
    assert snap.value("fcf_margin") == -0.1


def test_missing_capex_never_derives_fcf(db):
    c = _company(db)
    _f(db, c, "revenue", 1000)
    _f(db, c, "operating_cash_flow", 300)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("free_cash_flow") is None
    assert "normalized_fcf_or_fcf_margin" in snap.missing_inputs


def test_reported_fcf_wins(db):
    c = _company(db)
    _f(db, c, "revenue", 1000)
    _f(db, c, "free_cash_flow", 777)
    _f(db, c, "operating_cash_flow", 300)
    _f(db, c, "capital_expenditure", -100)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("free_cash_flow") == 777.0
    assert "free_cash_flow" not in snap.derived
