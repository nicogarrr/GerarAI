"""net_debt derivado de total_debt y cash_and_equivalents (mismo instante y unidad)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base as CoreBase  # noqa: F401
from app.models.entities import Base, Company, FinancialFact
from app.valuation.financial_snapshot import FinancialSnapshotBuilder


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.info["tenant_id"] = 1
        yield s
    eng.dispose()


def _company(db):
    c = Company(ticker="DND", name="Dnd", exchange="NASDAQ", company_type="growth",
                valuation_model="pre_revenue", factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _fact(db, c, metric, value, period="2026-06-30:Q2", unit="USD"):
    f = FinancialFact(company_id=c.id, metric=metric, value=Decimal(str(value)), unit=unit,
                      period=period, fiscal_year=2026, fiscal_quarter="Q2", source_type="SEC")
    db.add(f)
    db.commit()
    return f


def test_net_debt_derived_from_debt_and_cash(db):
    c = _company(db)
    _fact(db, c, "revenue", 70_918_000)
    _fact(db, c, "shares_diluted", 255_982_592)
    debt = _fact(db, c, "total_debt", 1_000_000_000)
    cash = _fact(db, c, "cash_and_equivalents", 400_000_000)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("net_debt") == 600_000_000.0
    assert snap.derived["net_debt"] == [debt.id, cash.id]
    assert "net_debt" not in snap.missing_inputs
    assert snap.facts["net_debt"].source_type == "DERIVED"
    assert snap.facts["net_debt"] not in db  # transient, never persisted


def test_reported_net_debt_wins_over_derivation(db):
    c = _company(db)
    _fact(db, c, "revenue", 1_000)
    _fact(db, c, "shares_diluted", 10)
    _fact(db, c, "net_debt", 5)
    _fact(db, c, "total_debt", 100)
    _fact(db, c, "cash_and_equivalents", 40)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("net_debt") == 5.0
    assert "net_debt" not in snap.derived


def test_no_derivation_when_one_input_missing_or_period_differs(db):
    c = _company(db)
    _fact(db, c, "revenue", 1_000)
    _fact(db, c, "shares_diluted", 10)
    _fact(db, c, "total_debt", 100)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("net_debt") is None
    assert "net_debt" in snap.missing_inputs
    _fact(db, c, "cash_and_equivalents", 40, period="2025-12-31:FY")
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("net_debt") is None


def test_derived_fact_is_safe_for_downstream_consumers(db):
    """Regresion: float(fact.confidence) fallaba (None) en thesis._build_claims."""
    from app.services.thesis_service import ThesisService

    c = _company(db)
    _fact(db, c, "revenue", 70_918_000)
    _fact(db, c, "shares_diluted", 255_982_592)
    _fact(db, c, "total_debt", 1_000_000_000)
    _fact(db, c, "cash_and_equivalents", 400_000_000)
    snap = FinancialSnapshotBuilder().build(db, c)
    nd = snap.facts["net_debt"]
    assert nd.confidence is not None and float(nd.confidence) > 0
    assert nd.is_reported is False and nd.is_adjusted is False
    claims = ThesisService()._build_claims(c, snap.facts, {"status": "partial"})
    nd_claim = next(x for x in claims if x["predicate"] == "net_debt")
    assert nd_claim["verification_state"] == "derived" and nd_claim["object"] == 600_000_000.0


def test_derived_net_debt_carries_shared_source_or_none(db):
    """Sin source_id el auditor marca el claim material como no soportado."""
    from app.services.source_auditor import SourceAuditor
    from app.services.thesis_service import ThesisService

    c = _company(db)
    _fact(db, c, "revenue", 70_918_000)
    _fact(db, c, "shares_diluted", 255_982_592)
    debt = _fact(db, c, "total_debt", 1_000_000_000)
    cash = _fact(db, c, "cash_and_equivalents", 400_000_000)
    debt.source_id = cash.source_id = 4242
    db.commit()
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.facts["net_debt"].source_id == 4242
    claims = ThesisService()._build_claims(c, snap.facts, {"status": "partial"})
    audit = SourceAuditor().audit(claims, {"x": 1})
    assert not any("deuda neta" in u.lower() or "net debt" in u.lower() for u in audit.unsupported_claims)

    cash.source_id = 4343
    db.commit()
    snap2 = FinancialSnapshotBuilder().build(db, c)
    assert snap2.facts["net_debt"].source_id is None


def _dated(db, c, metric, value, period, year=2025, quarter="FY", unit="USD"):
    f = FinancialFact(company_id=c.id, metric=metric, value=Decimal(str(value)), unit=unit,
                      period=period, fiscal_year=year, fiscal_quarter=quarter, source_type="SEC")
    db.add(f)
    db.commit()
    return f


def test_same_closing_date_with_different_period_labels_pairs(db):
    c = _company(db)
    _dated(db, c, "revenue", 1_000, "2025-12-31:FY")
    _dated(db, c, "shares_diluted", 10, "2025-12-31:FY")
    debt = _dated(db, c, "total_debt", 300, "2025-12-31:ANNUAL")
    cash = _dated(db, c, "cash_and_equivalents", 100, "2025-12-31")
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("net_debt") == 200.0
    assert snap.derived["net_debt"] == [debt.id, cash.id]


def test_newest_common_instant_is_used_when_latest_debt_has_no_matching_cash(db):
    c = _company(db)
    _dated(db, c, "revenue", 1_000, "2025-12-31:FY")
    _dated(db, c, "shares_diluted", 10, "2025-12-31:FY")
    _dated(db, c, "total_debt", 900, "2026-03-31:Q1", year=2026, quarter="Q1")
    debt = _dated(db, c, "total_debt", 300, "2025-12-31:FY")
    cash = _dated(db, c, "cash_and_equivalents", 100, "2025-12-31:FY")
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("net_debt") == 200.0
    assert snap.derived["net_debt"] == [debt.id, cash.id]


def test_different_closing_dates_never_pair(db):
    c = _company(db)
    _dated(db, c, "revenue", 1_000, "2025-12-31:FY")
    _dated(db, c, "shares_diluted", 10, "2025-12-31:FY")
    _dated(db, c, "total_debt", 300, "2025-12-31:FY")
    _dated(db, c, "cash_and_equivalents", 100, "2025-09-30:FY")
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.value("net_debt") is None
    assert "net_debt" in snap.missing_inputs
