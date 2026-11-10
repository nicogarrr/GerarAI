"""Informe: deuda de un agregador sin los arrendamientos operativos (regla «caja-deuda-v1» de la valoración).

Caso real (BD local, 9-nov-2026): Nautilus Biotechnology no tiene deuda financiera; el «total debt» de Yahoo al
31-dic-2025 (30.019.000 $) es exactamente su pasivo por arrendamiento operativo del 10-K. La valoración ya lo
dejaba en 0; el Informe enseñaba 30 M de deuda.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact, MarketPrice
from app.services.analyst_report import build_company_report


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _seed(db, *, debt, lease, debt_source="YAHOO_FUNDAMENTALS", lease_metric="operating_lease_liabilities"):
    company = Company(ticker="NAUT", name="NAUT", exchange="NASDAQ", currency="USD", sector="S", industry="I",
                      company_type="quality", valuation_model="unassigned", special_sources=[],
                      special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    db.add(MarketPrice(company_id=company.id, date=date(2026, 11, 6), open=2.23, high=2.23, low=2.23,
                       close=Decimal("2.23"), volume=1000, quote_currency="USD", source="test"))
    rows = [("total_debt", debt_source, debt), ("cash_and_equivalents", "SEC", 50_000_000),
            ("shares_outstanding", "SEC", 127_000_000)]
    if lease is not None:
        rows.append((lease_metric, "SEC", lease))
    for metric, source, value in rows:
        db.add(FinancialFact(company_id=company.id, metric=metric, value=Decimal(value), unit="USD",
                             period="2025-12-31:FY", fiscal_quarter="FY", source_type=source, is_reported=True))
    db.commit()
    return company


def _debt(db, **kw):
    return build_company_report(db, _seed(db, **kw), today=date(2026, 11, 9))["market"]["total_debt"]


def test_deuda_del_agregador_que_es_solo_arrendamiento_queda_en_cero(db):
    debt = _debt(db, debt=30_019_000, lease=30_019_000)
    assert debt["value"] == 0.0
    assert debt["provenance"] == "INFERIDO"
    assert debt["basis"] == "debt_minus_operating_leases"
    assert "30.0 M" in debt["formula"]


def test_se_resta_solo_el_arrendamiento(db):
    # ImmunityBio (BD local): Yahoo 518.075.000 − arrendamiento operativo del 10-K 40.982.000 = 477.093.000.
    debt = _debt(db, debt=518_075_000, lease=40_982_000)
    assert debt["value"] == pytest.approx(477_093_000)


def test_sin_arrendamiento_del_filing_o_deuda_primaria_no_se_toca(db):
    assert _debt(db, debt=30_019_000, lease=None)["value"] == 30_019_000


def test_deuda_del_filing_no_se_toca(db):
    assert _debt(db, debt=30_019_000, lease=30_019_000, debt_source="SEC")["value"] == 30_019_000


def test_ifrs_no_se_resta(db):
    # IFRS: los arrendamientos ya van en el total del agregador y en la deuda; no se descuentan.
    assert _debt(db, debt=30_019_000, lease=30_019_000, lease_metric="lease_liabilities")["value"] == 30_019_000
