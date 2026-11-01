"""InvestmentPlanService contract tests.

The plan is the user's savings discipline made measurable: one plan,
idempotent contribution imports, expected-vs-actual tracking with an
honest gap, and drift suggestions derived from real weights only.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models.entities import Base
from app.services.investment_plan_service import InvestmentPlanService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _plan(service, db, **overrides):
    args = {
        "monthly_contribution": Decimal("300"),
        # Divisa registrada explicitamente: sin ella el plan es legacy
        # «divisa no registrada» y los totales quedan en estado desconocido.
        "monthly_contribution_currency": "EUR",
        "start_date": date(2026, 1, 1),
        "horizon_years": 30,
        "target_allocations": [],
    }
    args.update(overrides)
    return service.upsert_plan(db, **args)


def test_no_plan_reports_absent_honestly(db):
    service = InvestmentPlanService()
    assert service.get_plan(db) is None
    assert service.plan_metrics(db) == {"plan_exists": False}
    assert service.list_contributions(db) == []
    with pytest.raises(ValueError, match="create it first"):
        service.add_contribution(db, date_=date(2026, 9, 1), amount=Decimal("300"))


def test_upsert_keeps_single_plan_and_updates_in_place(db):
    service = InvestmentPlanService()
    first = _plan(service, db)
    second = _plan(service, db, monthly_contribution=Decimal("450"))
    assert first.id == second.id
    assert service.get_plan(db).monthly_contribution == Decimal("450")


def test_contribution_external_id_import_is_idempotent(db):
    service = InvestmentPlanService()
    _plan(service, db)
    one = service.add_contribution(
        db, date_=date(2026, 9, 1), amount=Decimal("300"), external_id="broker-1"
    )
    two = service.add_contribution(
        db, date_=date(2026, 9, 1), amount=Decimal("300"), external_id="broker-1"
    )
    assert one.id == two.id
    assert len(service.list_contributions(db)) == 1
    assert service.delete_contribution(db, one.id) is True
    assert service.delete_contribution(db, one.id) is False


def test_plan_metrics_track_expected_vs_actual(db):
    service = InvestmentPlanService()
    _plan(service, db, monthly_contribution=Decimal("300"), start_date=date(2026, 7, 1))
    service.add_contribution(db, date_=date(2026, 7, 5), amount=Decimal("300"))
    service.add_contribution(db, date_=date(2026, 8, 5), amount=Decimal("300"))

    metrics = service.plan_metrics(db)
    assert metrics["plan_exists"] is True
    today = local_today()  # misma base que plan_metrics (hoy en Madrid)
    months = (today.year - 2026) * 12 + (today.month - 7)
    assert metrics["months_elapsed"] == months
    assert metrics["expected_contributions_base"] == pytest.approx(300 * months)
    assert metrics["actual_contributions_base"] == 600.0
    assert metrics["gap_base"] == pytest.approx(300 * months - 600)
    assert metrics["on_track"] == (300 * months <= 600)


def test_drift_suggestions_follow_target_bands(db):
    service = InvestmentPlanService()
    _plan(
        service, db,
        target_allocations=[
            {"kind": "sector", "label": "Tech", "target_pct": 60, "band_pct": 5},
            {"kind": "asset_class", "label": "Cash", "target_pct": 40, "band_pct": 5},
        ],
    )
    from app.models.entities import CashBalance, Company, Position

    company = Company(
        ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    db.add(
        Position(
            company_id=company.id, quantity=Decimal("10"), market_price=Decimal("100"),
            currency="EUR", market_value_base=Decimal("1000"), as_of=date(2026, 9, 20),
        )
    )
    db.add(CashBalance(currency="EUR", balance=Decimal("1000"), as_of=date(2026, 9, 20)))
    db.commit()

    drift = service.drift_analysis(db)
    assert drift["plan_exists"] is True
    assert drift["portfolio_value_base"] == pytest.approx(2000.0)
    assert drift["current_weights"]["Tech"] == pytest.approx(50.0)
    assert drift["current_weights"]["asset_class:Cash"] == pytest.approx(50.0)

    assert drift["status"] == "ok"
    assert drift["missing_fx"] == []
    deviations = {d["label"]: d for d in drift["deviations"]}
    assert deviations["Tech"]["within_band"] is False  # 50 vs 60+/-5
    assert deviations["Cash"]["within_band"] is False  # 50 vs 40+/-5
    suggestions = {(s["label"], s["direction"]): s for s in drift["suggestions"]}
    assert suggestions[("Tech", "buy")]["amount_base"] == pytest.approx(200.0)
    assert suggestions[("Cash", "sell")]["amount_base"] == pytest.approx(200.0)


def test_drift_excludes_cash_without_fx_rate_instead_of_guessing_parity(db):
    service = InvestmentPlanService()
    _plan(service, db)
    from app.models.entities import CashBalance

    db.add(CashBalance(currency="EUR", balance=Decimal("500"), as_of=date(2026, 9, 20)))
    db.add(CashBalance(currency="USD", balance=Decimal("900"), as_of=date(2026, 9, 20)))
    db.commit()

    drift = service.drift_analysis(db)
    # USD cash has no stored rate: excluded from the base total, never par-guessed.
    assert drift["status"] == "incomplete_fx"
    assert drift["missing_fx"] == [
        {
            "kind": "cash",
            "quote_currency": "USD",
            "base_currency": "EUR",
            "as_of": "2026-09-20",
        }
    ]
    assert drift["cash_base"] == pytest.approx(500.0)
    assert drift["portfolio_value_base"] == pytest.approx(500.0)


def test_drift_cash_uses_balance_date_like_portfolio_summary(db):
    from app.models.entities import CashBalance, FXRate
    from app.services.risk_service import RiskService
    service = InvestmentPlanService()
    _plan(service, db)
    db.add(CashBalance(currency="USD", balance=Decimal("1000"), as_of=date(2026, 9, 20)))
    db.add_all([
        FXRate(base_currency="EUR", quote_currency="USD", rate=Decimal("0.90"), rate_date=date(2026, 9, 19), source="test"),
        FXRate(base_currency="EUR", quote_currency="USD", rate=Decimal("0.95"), rate_date=date(2026, 9, 21), source="test"),
    ])
    db.commit()
    drift = service.drift_analysis(db)
    summary = RiskService().dashboard(db)
    assert drift["cash_base"] == pytest.approx(summary["total_value"])
    assert drift["cash_base"] == pytest.approx(900)
    assert drift["base_currency"] == "EUR"
    assert service.plan_metrics(db)["base_currency"] == "EUR"


def test_drift_weights_group_each_sector_with_its_tickers(db):
    """Un ticker de un sector ya listado no puede quedar bajo otro grupo."""
    service = InvestmentPlanService()
    _plan(
        service, db,
        target_allocations=[{"kind": "ticker", "label": "AAPL", "target_pct": 100, "band_pct": 5}],
    )
    from app.models.entities import CashBalance, Company, Position

    companies = [
        Company(ticker="GOOGL", name="Alphabet", exchange="NASDAQ", currency="USD",
                sector="Comms", industry="x", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
        Company(ticker="AAPL", name="Apple", exchange="NASDAQ", currency="USD",
                sector="Tech", industry="x", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
        Company(ticker="V", name="Visa", exchange="NYSE", currency="USD",
                sector="Fin", industry="x", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
        Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", currency="USD",
                sector="Tech", industry="x", company_type="holding",
                valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
    ]
    for comp in companies:
        db.add(comp)
    db.flush()
    for comp in companies:
        db.add(
            Position(
                company_id=comp.id, quantity=Decimal("10"), market_price=Decimal("100"),
                currency="EUR", market_value_base=Decimal("1000"), as_of=date(2026, 9, 20),
            )
        )
    db.add(CashBalance(currency="EUR", balance=Decimal("1000"), as_of=date(2026, 9, 20)))
    db.commit()

    drift = service.drift_analysis(db)
    keys = list(drift["current_weights"].keys())
    assert keys == ["Comms", "ticker:GOOGL", "Tech", "ticker:AAPL", "ticker:MSFT",
                    "Fin", "ticker:V", "asset_class:Cash"]
    # El detalle de la sugerencia no lleva signo "+": "por debajo" ya lo dice.
    assert drift["suggestions"][0]["detail"].startswith("AAPL está 80.0 puntos por debajo")


@pytest.mark.parametrize("updates", [
    {"date_": date(2026, 9, 2)}, {"amount": Decimal("301")}, {"currency": "USD"},
])
def test_contribution_same_external_key_with_changed_identity_is_conflict(db, updates):
    from app.services.investment_plan_service import ContributionConflict

    service = InvestmentPlanService()
    _plan(service, db)
    args = dict(date_=date(2026, 9, 1), amount=Decimal("300"), currency="EUR", external_id="same-import-key", note="original")
    first = service.add_contribution(db, **args)
    with pytest.raises(ContributionConflict):
        service.add_contribution(db, **{**args, **updates})
    db.expire(first)
    assert (first.date, first.amount, first.currency, first.note) == (date(2026, 9, 1), Decimal("300"), "EUR", "original")
    assert len(service.list_contributions(db)) == 1


def test_contribution_retry_keeps_stored_precision_and_note_is_not_identity(db):
    service = InvestmentPlanService()
    _plan(service, db)
    args = dict(date_=date(2026, 9, 1), amount=Decimal("300.001"), currency="EUR", external_id="same-import-key")
    first = service.add_contribution(db, **args, note="original")
    again = service.add_contribution(db, **args, note="retry note")
    assert again.id == first.id
    assert again.note == "original"


def test_contribution_conflict_handler_is_409_and_same_retry_still_succeeds(db):
    from fastapi import HTTPException

    from app.api.routes.plan import ContributionInput, add_contribution

    service = InvestmentPlanService()
    _plan(service, db)
    original = ContributionInput(date=date(2026, 9, 1), amount=300, currency="EUR", external_id="route-key")
    first = add_contribution(original, db)
    assert add_contribution(original, db)["id"] == first["id"]
    with pytest.raises(HTTPException) as caught:
        add_contribution(original.model_copy(update={"amount": 999}), db)
    assert caught.value.status_code == 409
    assert len(service.list_contributions(db)) == 1


@pytest.mark.parametrize("raw,expected", [("1.015", "1.02"), ("2.675", "2.68"), ("1.005", "1.01"), ("0.0149", "0.01")])
def test_contribution_half_cent_retry_has_same_explicit_precision_as_first_write(db, raw, expected):
    service = InvestmentPlanService()
    _plan(service, db)
    args = dict(date_=date(2026, 9, 1), amount=Decimal(raw), currency="EUR", external_id="half-cent")
    first = service.add_contribution(db, **args)
    assert first.amount == Decimal(expected)
    assert service.add_contribution(db, **args).id == first.id


@pytest.mark.parametrize("raw", ["0.001", "0.0049", "0", "-0.001", "-1"])
def test_contribution_rejects_nonpositive_rounded_amount_without_writes(db, raw):
    from sqlalchemy import func, select

    from app.models import PlanContribution

    service = InvestmentPlanService()
    _plan(service, db)
    with pytest.raises(ValueError, match="precisión de céntimos"):
        service.add_contribution(db, date_=date(2026, 9, 1), amount=Decimal(raw), external_id="too-small")
    assert db.scalar(select(func.count()).select_from(PlanContribution)) == 0


def test_contribution_half_cent_remains_positive(db):
    service = InvestmentPlanService()
    _plan(service, db)
    assert service.add_contribution(db, date_=date(2026, 9, 1), amount=Decimal("0.005")).amount == Decimal("0.01")


def test_contribution_route_rejects_positive_input_rounded_to_zero(db):
    from fastapi import HTTPException
    from sqlalchemy import func, select

    from app.api.routes.plan import ContributionInput, add_contribution
    from app.models import PlanContribution

    _plan(InvestmentPlanService(), db)
    payload = ContributionInput(date=date(2026, 9, 1), amount=0.001)
    with pytest.raises(HTTPException) as caught:
        add_contribution(payload, db)
    assert caught.value.status_code == 400
    assert "precisión de céntimos" in caught.value.detail
    assert db.scalar(select(func.count()).select_from(PlanContribution)) == 0
