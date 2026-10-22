"""Contrato de divisa de la cuota mensual del plan (F-nuevo).

monthly_contribution_currency es aditiva y NULL en planes legacy:
- NULL = «divisa no registrada»: los totales NUNCA se inventan.
- Omitida al actualizar (cliente viejo): se preserva la registrada.
- null explicito al actualizar: se desregistra conscientemente.
- Divisa distinta de la base: conversion por periodo en el aniversario
  mensual de start_date (clamp fin de mes, sin lookahead); un periodo sin
  tasa deja el total en None y se declara, nunca parcial como completo.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate
from app.services.investment_plan_service import (
    PLAN_CURRENCY_UNSET,
    InvestmentPlanService,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _plan(service, db, **overrides):
    args = {
        "monthly_contribution": Decimal("500"),
        "start_date": date(2026, 1, 15),
        "horizon_years": 30,
        "target_allocations": [],
    }
    args.update(overrides)
    return service.upsert_plan(db, **args)


def test_legacy_omitted_currency_never_invents_totals(db):
    service = InvestmentPlanService()
    plan = _plan(service, db)  # omiso -> NULL desconocido
    assert plan.monthly_contribution_currency is None
    metrics = service.plan_metrics(db)
    assert metrics["monthly_contribution"] == 500.0
    assert metrics["monthly_contribution_currency"] is None
    assert metrics["monthly_currency_recorded"] is False
    assert metrics["expected_contributions_base"] is None
    assert metrics["gap_base"] is None
    assert metrics["on_track"] is None


def test_update_omitted_currency_preserves_registered(db):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution_currency="USD")
    _plan(service, db, monthly_contribution=Decimal("600"))  # omiso
    assert service.get_plan(db).monthly_contribution_currency == "USD"


def test_update_explicit_null_unregisters_currency(db):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution_currency="USD")
    _plan(service, db, monthly_contribution_currency=None)  # explicito
    assert service.get_plan(db).monthly_contribution_currency is None
    assert service.plan_metrics(db)["monthly_currency_recorded"] is False


def test_same_currency_math_unchanged(db):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution_currency="EUR")  # cartera EUR
    metrics = service.plan_metrics(db)
    months = metrics["months_elapsed"]
    assert metrics["expected_contributions_base"] == pytest.approx(500 * months)
    assert metrics["expected_missing_fx"] == []


def _two_month_start() -> tuple[date, date, date]:
    """start con months_elapsed=2 y aniversarios <= hoy."""
    today = date.today()
    start = date(today.year, today.month, 1)
    start = InvestmentPlanService._add_months_clamped(start, -2)
    first = InvestmentPlanService._add_months_clamped(start, 1)
    second = InvestmentPlanService._add_months_clamped(start, 2)
    assert second <= today
    return start, first, second


def test_cross_currency_converts_per_period_with_dated_rates(db):
    service = InvestmentPlanService()
    start, first, second = _two_month_start()
    _plan(service, db, start_date=start, monthly_contribution_currency="USD")
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate=Decimal("0.9"), rate_date=first, source="test"))
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate=Decimal("0.8"), rate_date=second, source="test"))
    db.commit()
    metrics = service.plan_metrics(db)
    assert metrics["months_elapsed"] == 2
    assert metrics["expected_contributions_base"] == pytest.approx(500 * 0.9 + 500 * 0.8)
    assert metrics["expected_missing_fx"] == []


def test_cross_currency_missing_rate_keeps_totals_unknown(db):
    """Politica FX existente: ultima tasa <= fecha (carry-forward). Un periodo
    solo queda sin tasa si NO hay ninguna anterior: aqui la unica tasa es la
    del periodo 2, asi que el periodo 1 se declara y el total sigue None."""
    service = InvestmentPlanService()
    start, _first, second = _two_month_start()
    _plan(service, db, start_date=start, monthly_contribution_currency="USD")
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate=Decimal("0.8"), rate_date=second, source="test"))
    db.commit()
    metrics = service.plan_metrics(db)
    assert metrics["expected_contributions_base"] is None
    assert metrics["expected_contributions_converted_base"] == pytest.approx(400)
    assert len(metrics["expected_missing_fx"]) == 1
    assert metrics["expected_missing_fx"][0]["period"] == 1
    assert metrics["gap_base"] is None
    assert metrics["on_track"] is None


def test_cross_currency_rate_carries_forward_from_earlier_date(db):
    service = InvestmentPlanService()
    start, first, _second = _two_month_start()
    _plan(service, db, start_date=start, monthly_contribution_currency="USD")
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate=Decimal("0.9"), rate_date=first, source="test"))
    db.commit()
    metrics = service.plan_metrics(db)
    assert metrics["expected_missing_fx"] == []
    assert metrics["expected_contributions_base"] == pytest.approx(900)


def test_monthly_anniversary_clamps_to_month_end():
    clamp = InvestmentPlanService._add_months_clamped
    assert clamp(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert clamp(date(2024, 1, 31), 1) == date(2024, 2, 29)  # bisiesto
    assert clamp(date(2026, 1, 15), 1) == date(2026, 2, 15)


def test_quota_dates_never_use_future_rates(db):
    """Un aniversario aun no alcanzado se acota a hoy: una tasa fechada en
    el futuro (despues del aniversario real, antes de hoy no aplica) no se
    lee con lookahead."""
    service = InvestmentPlanService()
    today = date.today()
    future_day = min(today.day + 1, 28)
    start = InvestmentPlanService._add_months_clamped(
        date(today.year, today.month, future_day), -1
    )
    _plan(service, db, start_date=start, monthly_contribution_currency="USD")
    # Tasa futura respecto al aniversario real (dia future_day de este mes):
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate=Decimal("9.9"), rate_date=today + timedelta(days=10),
                  source="test"))
    db.commit()
    metrics = service.plan_metrics(db)
    # Sin tasa valida <= hoy: total desconocido, no inventado con la futura.
    assert metrics["expected_contributions_base"] is None


def test_drift_exposes_next_contribution_currency(db):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution_currency="USD")
    drift = service.drift_analysis(db)
    if drift.get("plan_exists"):
        assert drift["next_contribution"] == 500.0
        assert drift["next_contribution_currency"] == "USD"
