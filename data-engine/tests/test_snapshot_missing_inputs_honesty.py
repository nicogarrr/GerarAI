"""Hallazgo QA ASML: sin ancla de revenue, las entradas presentes son
«no utilizables», no «ausentes».

La vista ?view=sources declaraba «Faltan entradas: revenue, shares_diluted,
free_cash_flow_or_fcf_margin» mientras ?view=financials mostraba «Acciones
diluidas (media) 2025-12-31:FY 388,9 M SEC»: el corte temprano del snapshot
declaraba las tres ausentes sin comprobarlo. Estos tests pinean la
distincion: solo falta lo que falta de verdad. El builder point-in-time se
cubria aqui tambien, pero #1227 lo elimina como codigo muerto, asi que la
PR queda reducida al builder actual.
"""

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
    c = Company(ticker="ASML", name="ASML Holding", exchange="NASDAQ", company_type="growth",
                valuation_model="standard_dcf", factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _fact(db, c, metric, value):
    f = FinancialFact(company_id=c.id, metric=metric, value=Decimal(str(value)), unit="EUR",
                      period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY", source_type="SEC")
    db.add(f)
    db.commit()
    return f


def test_shares_present_without_revenue_is_not_reported_missing(db):
    """El caso ASML: shares_diluted 388,9 M existe; el aviso no puede
    declararlo ausente."""
    c = _company(db)
    _fact(db, c, "shares_diluted", 388_900_000)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.missing_inputs == ["revenue", "free_cash_flow_or_fcf_margin"]
    assert not snap.coherent
    assert any("acciones diluidas guardadas" in w and "falta" in w for w in snap.warnings)


def test_everything_absent_keeps_the_full_missing_list(db):
    c = _company(db)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert snap.missing_inputs == ["revenue", "shares_diluted", "free_cash_flow_or_fcf_margin"]
    assert snap.warnings == []


def test_fcf_present_without_revenue_is_not_reported_missing(db):
    c = _company(db)
    _fact(db, c, "free_cash_flow", 5_000_000_000)
    snap = FinancialSnapshotBuilder().build(db, c)
    assert "free_cash_flow_or_fcf_margin" not in snap.missing_inputs
    assert "shares_diluted" in snap.missing_inputs
    assert any("flujo de caja libre guardado" in w for w in snap.warnings)
