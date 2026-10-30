"""Contrato de divisa de la cuota mensual del plan (F-nuevo).

monthly_contribution_currency es aditiva y NULL en planes legacy:
- NULL = «divisa no registrada»: los totales NUNCA se inventan.
- Omitida al actualizar (cliente viejo): se preserva la registrada.
- null explicito al actualizar: se desregistra conscientemente.
- Divisa distinta de la base: conversion por periodo en el aniversario
  mensual de start_date (clamp fin de mes, sin lookahead); un periodo sin
  tasa deja el total en None y se declara, nunca parcial como completo.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, FXRate
from app.services.investment_plan_service import (
    InvestmentPlanService,
)


@pytest.fixture(autouse=True)
def contract_on(monkeypatch):
    """Los tests de este fichero ejercitan el contrato ON salvo los marcados OFF."""
    monkeypatch.setenv("PLAN_CURRENCY_ENFORCED", "1")


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
    # La cuota del 25-mar aun no vence: no se debe y no bloquea el total
    # (antes: None => «En camino» N/D hasta cada aniversario).
    assert m["expected_conversion_complete"] is True
    assert m["expected_contributions_base"] == pytest.approx(450)
    assert m["expected_missing_fx"] == []
    assert m["on_track"] is not None


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


def test_same_currency_counts_only_due_installments(db):
    service = InvestmentPlanService()
    _plan(service, db, start_date=date(2026, 1, 25), monthly_contribution_currency="EUR")
    m = service.plan_metrics(db, today=TODAY)  # 25-mar aun no vencida
    assert m["months_elapsed"] == 2
    # La cuota del 25-mar aun no vence: solo 1 cuota exigible (igual que la via FX).
    assert m["expected_contributions_base"] == pytest.approx(500)


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


# --- Capability OFF (default): combinaciones seguras, sin reinterpretar ---

def test_off_legacy_null_keeps_previous_math(db, monkeypatch):
    monkeypatch.delenv("PLAN_CURRENCY_ENFORCED", raising=False)
    service = InvestmentPlanService()
    _plan(service, db, start_date=date(2026, 1, 15))  # NULL
    m = service.plan_metrics(db, today=TODAY)
    assert m["currency_contract_enabled"] is False
    assert m["expected_basis"] == "legacy_monthly_as_base"
    assert m["expected_contributions_base"] == pytest.approx(1000)


def test_off_registered_same_as_base_keeps_previous_math(db, monkeypatch):
    monkeypatch.delenv("PLAN_CURRENCY_ENFORCED", raising=False)
    service = InvestmentPlanService()
    _plan(service, db, start_date=date(2026, 1, 15), monthly_contribution_currency="EUR")
    m = service.plan_metrics(db, today=TODAY)
    assert m["expected_basis"] == "legacy_monthly_as_base"
    assert m["expected_contributions_base"] == pytest.approx(1000)


def test_off_registered_usd_in_eur_base_is_blocked_not_reinterpreted(db, monkeypatch):
    """Plan guardado con ON como USD y flag apagado despues: NO se calcula
    500 USD como 500 EUR; totales null y base explicita."""
    monkeypatch.setenv("PLAN_CURRENCY_ENFORCED", "1")
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 15))
    monkeypatch.delenv("PLAN_CURRENCY_ENFORCED")
    m = service.plan_metrics(db, today=TODAY)
    assert m["expected_basis"] == "blocked_contract_disabled"
    assert m["expected_contributions_base"] is None
    assert m["gap_base"] is None and m["on_track"] is None
    assert m["monthly_contribution_currency"] == "USD"  # dato conservado


def test_on_exposes_capability_and_basis(db):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution_currency="EUR")
    m = service.plan_metrics(db, today=TODAY)
    assert m["currency_contract_enabled"] is True
    assert m["expected_basis"] == "plan_currency"
    _plan(service, db, monthly_contribution_currency=None)
    assert service.plan_metrics(db, today=TODAY)["expected_basis"] == "unknown_currency"


def _put(db, **fields):
    from app.api.routes.plan import PlanUpsertInput, upsert_plan
    base = {"monthly_contribution": 500, "start_date": date(2026, 1, 15)}
    return upsert_plan(PlanUpsertInput(**base, **fields), db)


def test_off_rejects_explicit_currency_write_instead_of_ignoring(db, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.delenv("PLAN_CURRENCY_ENFORCED", raising=False)
    for fields in ({"monthly_contribution_currency": "EUR"},
                   {"monthly_contribution_currency": None}):
        with pytest.raises(HTTPException) as err:
            _put(db, **fields)
        assert err.value.status_code == 409
        assert err.value.detail == "plan_currency_contract_disabled"
    assert InvestmentPlanService().get_plan(db) is None  # nada guardado


def test_off_accepts_old_client_write_without_currency(db, monkeypatch):
    monkeypatch.delenv("PLAN_CURRENCY_ENFORCED", raising=False)
    out = _put(db)
    assert out["monthly_contribution_currency"] is None


def test_on_put_explicit_registers_and_omitted_preserves(db):
    assert _put(db, monthly_contribution_currency="usd")["monthly_contribution_currency"] == "USD"
    assert _put(db)["monthly_contribution_currency"] == "USD"  # omitido preserva
    assert _put(db, monthly_contribution_currency=None)["monthly_contribution_currency"] is None


def test_old_client_amount_change_on_non_eur_registered_plan_is_rejected(db):
    from fastapi import HTTPException
    _put(db, monthly_contribution_currency="USD")
    with pytest.raises(HTTPException) as err:
        from app.api.routes.plan import PlanUpsertInput, upsert_plan
        upsert_plan(PlanUpsertInput(monthly_contribution=300, start_date=date(2026, 1, 15)), db)
    assert err.value.status_code == 409
    assert err.value.detail == "plan_currency_required_for_amount_change"
    assert InvestmentPlanService().get_plan(db).monthly_contribution == Decimal("500")


def test_old_client_same_amount_on_registered_plan_preserves_currency(db):
    _put(db, monthly_contribution_currency="USD")
    out = _put(db)  # mismo importe 500, solo otros campos
    assert out["monthly_contribution_currency"] == "USD"


def test_drift_off_registered_not_base_blocks_next_contribution(db, monkeypatch):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution_currency="USD")
    monkeypatch.delenv("PLAN_CURRENCY_ENFORCED")
    drift = service.drift_analysis(db)
    assert drift["plan_exists"] is True
    assert drift["next_contribution"] is None
    assert drift["next_contribution_basis"] == "blocked_contract_disabled"
    assert drift["next_contribution_currency"] == "USD"


def test_get_plan_without_plan_exposes_capability(db, monkeypatch):
    from app.api.routes.plan import get_plan
    assert get_plan(db) == {"plan_exists": False, "currency_contract_enabled": True}
    monkeypatch.delenv("PLAN_CURRENCY_ENFORCED")
    assert get_plan(db)["currency_contract_enabled"] is False


def test_fx_and_same_currency_agree_on_due_installments(db):
    """Misma cuota, misma fecha: con tasa 1 la via FX debe exigir lo mismo que la via sin FX."""
    service = InvestmentPlanService()
    _usd_plan(service, db, date(2026, 1, 31))
    _rate(db, "1", date(2026, 1, 1))
    m = service.plan_metrics(db, today=date(2026, 4, 29))  # 30-abr aun no vence
    assert m["expected_contributions_base"] == pytest.approx(1000)  # feb + mar
    assert [p["status"] for p in m["expected_periods"]] == ["converted", "converted", "pending_due_date"]
