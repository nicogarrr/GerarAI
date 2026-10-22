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
    metrics = service.plan_metrics(db, today=date(2026, 4, 20))
    months = metrics["months_elapsed"]
    assert months == 3
    assert metrics["expected_contributions_base"] == pytest.approx(500 * months)
    assert metrics["expected_missing_fx"] == []


TODAY = date(2026, 3, 20)  # reloj fijo: ningun test depende del dia actual


def _usd_plan(service, db, start):
    _plan(service, db, start_date=start, monthly_contribution_currency="USD")


def _rate(db, rate, on, source="test"):
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate=Decimal(rate), rate_date=on, source=source))
    db.commit()


def test_cross_currency_converts_per_period_with_dated_rates(db):
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 15))  # vencen 15-feb y 15-mar
    _rate(db, "0.9", date(2026, 2, 15))
    _rate(db, "0.8", date(2026, 3, 15))
    m = service.plan_metrics(db, today=TODAY)
    assert m["months_elapsed"] == 2
    assert m["expected_contributions_base"] == pytest.approx(500 * 0.9 + 500 * 0.8)
    assert m["expected_conversion_complete"] is True
    assert m["expected_missing_fx"] == []


def test_missing_rate_on_due_period_keeps_totals_unknown(db):
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 15))
    _rate(db, "0.8", date(2026, 3, 15))  # nada <= 15-feb
    m = service.plan_metrics(db, today=TODAY)
    assert m["expected_contributions_base"] is None
    assert m["expected_contributions_converted_base"] == pytest.approx(400)
    assert [x["period"] for x in m["expected_missing_fx"]] == [1]
    assert m["expected_missing_fx"][0]["reason"] == "no_rate_on_or_before_due_date"
    assert m["gap_base"] is None and m["on_track"] is None


def test_rate_carries_forward_from_earlier_date(db):
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 15))
    _rate(db, "0.9", date(2026, 2, 1))
    m = service.plan_metrics(db, today=TODAY)
    assert m["expected_missing_fx"] == []
    assert m["expected_contributions_base"] == pytest.approx(900)


def test_partial_month_future_anniversary_is_pending_not_converted(db):
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 25))  # 25-feb vencida, 25-mar FUTURA
    _rate(db, "0.9", date(2026, 2, 1))
    _rate(db, "9.9", date(2026, 3, 20))  # tasa de hoy: no debe atribuirse al 25-mar
    m = service.plan_metrics(db, today=TODAY)
    assert m["months_elapsed"] == 2
    statuses = [p["status"] for p in m["expected_periods"]]
    assert statuses == ["converted", "pending_due_date"]
    pending = m["expected_periods"][1]
    assert pending["due_date"] == "2026-03-25"
    assert pending["rate"] is None and pending["rate_date"] is None and pending["source"] is None
    assert m["expected_conversion_complete"] is False
    assert m["expected_contributions_base"] is None
    assert m["expected_missing_fx"] == []


def test_leap_day_and_month_end_anniversaries_are_deterministic(db):
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2024, 1, 31))
    _rate(db, "0.9", date(2024, 1, 1))
    m = service.plan_metrics(db, today=date(2024, 3, 31))
    due = [p["due_date"] for p in m["expected_periods"]]
    assert due == ["2024-02-29", "2024-03-31"]
    assert m["expected_conversion_complete"] is True


def test_monthly_anniversary_clamps_to_month_end():
    clamp = InvestmentPlanService._add_months_clamped
    assert clamp(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert clamp(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert clamp(date(2026, 1, 15), 1) == date(2026, 2, 15)


def test_same_currency_uses_calendar_month_count_even_if_not_due(db):
    service = InvestmentPlanService()
    _plan(service, db, start_date=date(2026, 1, 25), monthly_contribution_currency="EUR")
    m = service.plan_metrics(db, today=TODAY)  # 25-mar aun no vencida
    assert m["months_elapsed"] == 2
    assert m["expected_contributions_base"] == pytest.approx(1000)  # compat


def test_drift_exposes_next_contribution_currency(db):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution_currency="USD")
    drift = service.drift_analysis(db)
    if drift.get("plan_exists"):
        assert drift["next_contribution"] == 500.0
        assert drift["next_contribution_currency"] == "USD"


def test_periods_expose_rate_date_source_and_direction(db):
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 15))
    _rate(db, "0.9", date(2026, 2, 1), source="ecb")
    _rate(db, "0.8", date(2026, 3, 15), source="manual")
    first, second = service.plan_metrics(db, today=TODAY)["expected_periods"]
    assert (first["rate_date"], first["rate"], first["source"], first["direction"]) == (
        "2026-02-01", 0.9, "ecb", "direct")
    assert (second["rate_date"], second["source"]) == ("2026-03-15", "manual")


def test_inverse_rate_reports_inverse_source_and_reciprocal(db):
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 15))
    db.add(FXRate(base_currency="USD", quote_currency="EUR",
                  rate=Decimal("2"), rate_date=date(2026, 2, 1), source="inv-src"))
    db.commit()
    period = service.plan_metrics(db, today=date(2026, 2, 20))["expected_periods"][0]
    assert period["direction"] == "inverse"
    assert period["rate"] == pytest.approx(0.5)
    assert period["source"] == "inv-src"
    assert period["rate_date"] == "2026-02-01"
