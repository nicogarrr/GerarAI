"""Acciones y precio en la misma base alrededor de un split.

El corte de splits es la fecha del precio. Si el ultimo cierre guardado es
anterior a un split ya efectivo, su base es desconocida (vieja si no hubo
refresco; ya ajustada si un refresco reescribio la serie antes de la primera
sesion nueva): el valor por accion va en la base actual y el precio no se
compara (MOS y DCF inverso N/D).
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
from app.valuation.engines.relative_multiples import _fundamentals
from app.valuation.engines.standard_dcf import StandardDCFEngine
from app.valuation.fact_reference import latest_facts, split_scaled_value
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
            ("eps_diluted", 1.5, "USD/shares"),
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


def test_valuation_with_a_pre_split_close_does_not_compare_the_price():
    """Cierre del 30-05, split 4:1 del 02-06: ese cierre puede estar en la base
    vieja (sin refresco) o ya ajustado (refresco antes de la primera sesion
    nueva). Valor por accion en la base actual (400 acciones) y MOS N/D."""
    db, company = _db()
    try:
        before = ValuationService().value_company(db, company)
        _split(db, company)
        after = ValuationService().value_company(db, company)
    finally:
        db.close()
    assert before["expected_value"] is not None
    assert before["margin_of_safety"] is not None
    assert after["expected_value"] == pytest.approx(before["expected_value"] / 4)
    assert after["margin_of_safety"] is None
    assert after["trace"]["price_status"] == "price_basis_unknown_after_split"


def test_valuation_with_a_post_split_close_compares_in_the_new_basis():
    db, company = _db()
    try:
        before = ValuationService().value_company(db, company)
        _split(db, company)
        db.add(MarketPrice(
            company_id=company.id, date=SPLIT_DAY, open=Decimal("5"), high=Decimal("5"),
            low=Decimal("5"), close=Decimal("5"), adj_close=Decimal("5"), volume=1000,
            source="TEST",
        ))
        db.commit()
        after = ValuationService().value_company(db, company)
    finally:
        db.close()
    # 20 / 4 = 5 en la base nueva: mismo MOS que antes del split.
    assert after["expected_value"] == pytest.approx(before["expected_value"] / 4)
    assert after["margin_of_safety"] == pytest.approx(before["margin_of_safety"])


def test_long_term_reverse_dcf_with_a_pre_split_close_is_not_evaluable():
    db, company = _db()
    try:
        before = LongTermModelService().build(db, company, commit=False)
        _split(db, company)
        after = LongTermModelService().build(db, company, commit=False)
    finally:
        db.close()
    assert before["reverse_dcf"].get("required_revenue_growth") is not None
    assert after["reverse_dcf"]["status"] == "insufficient_data"
    assert after["reverse_dcf"]["missing_inputs"] == ["price_basis_after_split"]


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


def test_fact_reference_uses_the_price_date_as_split_cutoff():
    """Motores DDM/FCFE, utilities, multiplos, SOTP y sectoriales leen por aqui."""
    db, company = _db()
    try:
        _split(db, company)
        stale = latest_facts(db, company.id, ["shares_diluted", "eps_diluted"], cutoff=PRE_SPLIT_CLOSE_DAY)
        fresh = latest_facts(db, company.id, ["shares_diluted", "eps_diluted"], cutoff=SPLIT_DAY)
        today = latest_facts(db, company.id, ["shares_diluted", "eps_diluted"])
        row = db.query(FinancialFact).filter_by(metric="shares_diluted", fiscal_year=2024).one()
        scaled_stale = split_scaled_value(db, company.id, row, cutoff=PRE_SPLIT_CLOSE_DAY)
        own_stale = _fundamentals(db, company.id, cutoff=PRE_SPLIT_CLOSE_DAY)
    finally:
        db.close()
    assert stale["shares_diluted"].value == pytest.approx(100.0)
    assert stale["eps_diluted"].value == pytest.approx(1.5)
    assert fresh["shares_diluted"].value == pytest.approx(400.0)
    assert fresh["eps_diluted"].value == pytest.approx(0.375)
    # Sin corte: hoy (comportamiento anterior para quien no pasa fecha).
    assert today["shares_diluted"].value == pytest.approx(400.0)
    assert scaled_stale == pytest.approx(100.0)
    assert own_stale["shares_diluted"] == pytest.approx(100.0)


def test_context_split_cutoff_is_the_price_date():
    db, company = _db()
    try:
        context = StandardDCFEngine().build_context(
            db, company, 20.0, None, price_as_of=PRE_SPLIT_CLOSE_DAY
        )
        replay = StandardDCFEngine().build_context(db, company, 20.0, date(2025, 3, 31))
    finally:
        db.close()
    assert context.split_cutoff == PRE_SPLIT_CLOSE_DAY
    assert replay.split_cutoff == date(2025, 3, 31)
