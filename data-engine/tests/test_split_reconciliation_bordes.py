"""Borde de ``split_reconciliation``: ambito por tenant de sesion.

Lo que demuestra: con ``tenant_id=None`` y ``all_tenants=False``,
``_load_rows`` aplica los predicados de ``tenant_filters`` tomados de
``db.info["tenant_id"]`` (rama 153-155): solo entran las filas del tenant
de la sesion, las de otros tenants quedan fuera del plan.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, CorporateAction, Tenant
from app.services.split_reconciliation import plan_split_reconciliation


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker):
    c = Company(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency="USD",
        sector="Tech",
        industry="Tech",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(c)
    db.commit()
    return c


def _tenant(db, ext):
    t = Tenant(external_id=ext, name=ext, metadata_={})
    db.add(t)
    db.commit()
    return t


def _split(db, company, day, ratio, tenant):
    row = CorporateAction(
        company_id=company.id,
        action_type="split",
        effective_date=day,
        ratio=Decimal(ratio),
        applied=False,
        source="yahoo_finance",
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        tenant_id=tenant.id,
    )
    db.add(row)
    db.commit()
    return row


def test_sin_parametro_filtra_por_tenant_de_sesion(db):
    t1, t2 = _tenant(db, "sr-ext-1"), _tenant(db, "sr-ext-2")
    c = _company(db, "SRAC")
    # Dos splits duplicados en cada tenant: con el filtro solo se ve el
    # par del tenant de la sesion.
    _split(db, c, date(2020, 8, 31), "4", t1)
    _split(db, c, date(2020, 8, 31), "4", t1)
    _split(db, c, date(2020, 8, 31), "4", t2)
    _split(db, c, date(2020, 8, 31), "4", t2)
    db.info["tenant_id"] = t1.id
    plan = plan_split_reconciliation(db, tenant_id=None, all_tenants=False)
    body = plan.as_dict()
    assert body["rows_examined"] == 2
    assert body["duplicate_group_count"] == 1
    assert body["proposed_removal_count"] == 1
