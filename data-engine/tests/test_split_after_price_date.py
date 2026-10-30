"""Acciones en la base del PRECIO con el que se comparan.

El ultimo cierre guardado puede ser anterior a un split (el refresco de precios
aun no ha pasado): ese cierre esta en la base vieja. Ajustar las acciones del
ultimo 10-K por ese split (corte = hoy) dividia el valor por accion entre el
ratio frente a un precio sin dividir: con un 4:1, valor razonable /4 y margen
de seguridad hundido; en el modelo a largo plazo, el DCF inverso resolvia con
4x acciones.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, CorporateAction, FinancialFact, MarketPrice
from app.services.long_term_model_service import LongTermModelService, _adjust_share_facts
from app.services.valuation_service import ValuationService
from app.valuation.financial_snapshot import FinancialSnapshotBuilder

SPLIT_DAY = date(2025, 6, 2)
PRE_SPLIT_CLOSE_DAY = date(2025, 5, 30)


def _db() -> tuple[Session, Company]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = "tenant-test"
    company = Company(
        ticker="SPLT", name="Split Co", currency="USD", exchange="NYSE",
        sector="Tech", industry="Software", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    for year, revenue in ((2022, 800.0), (2023, 900.0), (2024, 1000.0)):
        for metric, value, unit in (
            ("revenue", revenue, "USD"),
            ("net_income", revenue * 0.15, "USD"),
            ("free_cash_flow", revenue * 0.10, "USD"),
            ("net_debt", 0.0, "USD"),
            ("shares_diluted", 100.0, "shares"),
        ):
            db.add(FinancialFact(
                company_id=company.id, metric=metric, value=Decimal(str(value)), unit=unit,
                period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY",
                filed=date(year + 1, 2, 20), source_type="SEC", is_reported=True,
                confidence=Decimal("1"),
            ))
    # Ultimo cierre guardado: viernes ANTERIOR al split (base vieja).
    db.add(MarketPrice(
        company_id=company.id, date=PRE_SPLIT_CLOSE_DAY, open=Decimal("20"), high=Decimal("20"),
        low=Decimal("20"), close=Decimal("20"), adj_close=Decimal("20"), volume=1000,
        source="TEST",
    ))
    db.commit()
    return db, company


def _split(db: Session, company: Company) -> None:
    db.add(CorporateAction(
        company_id=company.id, action_type="split", effective_date=SPLIT_DAY,
        ratio=Decimal("4"), description="split 4:1",
    ))
    db.commit()


def test_snapshot_uses_the_price_date_as_split_cutoff():
    db, company = _db()
    try:
        _split(db, company)
        stale = FinancialSnapshotBuilder().build(db, company, price_as_of=PRE_SPLIT_CLOSE_DAY)
        fresh = FinancialSnapshotBuilder().build(db, company, price_as_of=SPLIT_DAY)
    finally:
        db.close()
    # Cierre del 30-05 (antes del split): 100 acciones, sin factor.
    assert stale.value("shares_diluted") == pytest.approx(100.0)
    assert "shares_diluted" not in stale.split_factors
    # Cierre del mismo dia del split (ya en base nueva): 400.
    assert fresh.value("shares_diluted") == pytest.approx(400.0)


def test_valuation_with_a_pre_split_close_matches_the_unsplit_valuation():
    db, company = _db()
    try:
        before = ValuationService().value_company(db, company)
        _split(db, company)
        after = ValuationService().value_company(db, company)
    finally:
        db.close()
    assert before["expected_value"] is not None
    # Mismo precio (20, base vieja) y mismas acciones (100): mismo valor y MOS.
    assert after["expected_value"] == pytest.approx(before["expected_value"])
    assert after["margin_of_safety"] == pytest.approx(before["margin_of_safety"])


def test_long_term_reverse_dcf_with_a_pre_split_close_keeps_old_share_basis():
    db, company = _db()
    try:
        before = LongTermModelService().build(db, company, commit=False)
        _split(db, company)
        after = LongTermModelService().build(db, company, commit=False)
    finally:
        db.close()
    growth_before = before["reverse_dcf"].get("required_revenue_growth")
    assert growth_before is not None
    assert after["reverse_dcf"]["required_revenue_growth"] == pytest.approx(growth_before)


def test_adjust_share_facts_ignores_splits_after_the_cutoff():
    fact = FinancialFact(
        metric="shares_diluted", value=Decimal("100"), unit="shares",
        period="2024-12-31:FY", fiscal_year=2024, filed=date(2025, 2, 20),
    )
    split = CorporateAction(action_type="split", effective_date=SPLIT_DAY, ratio=Decimal("4"))
    (kept,) = _adjust_share_facts([fact], [split], cutoff=PRE_SPLIT_CLOSE_DAY)
    (scaled,) = _adjust_share_facts([fact], [split], cutoff=SPLIT_DAY)
    assert float(kept.value) == pytest.approx(100.0)
    assert float(scaled.value) == pytest.approx(400.0)
