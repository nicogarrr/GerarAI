"""Tests hermeticos del tearsheet de portfolio (sin red, sin ficheros).

Run from data-engine/:
    pytest tests/test_tearsheet_service.py -v
"""

import math
import statistics
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Company,
    Portfolio,
    PortfolioDailySnapshot,
    PositionDailySnapshot,
    Tenant,
)
from app.services.tearsheet_service import (
    TearsheetService,
    compute_metrics,
    exposure_from_snapshot,
)

# Serie determinista: mezcla de dias positivos y negativos.
RETURNS = [0.01, -0.005, 0.02, -0.015, 0.008, 0.003, -0.002, 0.012]


def test_compute_metrics_matches_hand_calculation():
    result = compute_metrics(RETURNS, periods=252, risk_free=0.0)

    assert result["status"] == "ok"
    assert result["n_observations"] == len(RETURNS)

    mean = statistics.mean(RETURNS)
    vol = statistics.stdev(RETURNS)
    assert result["sharpe"] == pytest.approx(mean / vol * math.sqrt(252), rel=1e-9)

    # Sortino & Price (1994): desviacion a la baja sobre N, objetivo 0.
    # Negativos: -0.005, -0.015, -0.002 -> suma cuadrados 0.000254;
    # DD = sqrt(0.000254 / 8) = 0.0056347; media 0.003875 -> Sortino ~ 10.917.
    downside_dev = math.sqrt(sum(min(r, 0.0) ** 2 for r in RETURNS) / len(RETURNS))
    assert result["sortino"] == pytest.approx(
        mean / downside_dev * math.sqrt(252), rel=1e-9
    )
    assert result["sortino"] == pytest.approx(10.917, rel=1e-3)

    wealth, peak, mdd = 1.0, 1.0, 0.0
    for r in RETURNS:
        wealth *= 1.0 + r
        peak = max(peak, wealth)
        mdd = min(mdd, (wealth - peak) / peak)
    assert result["max_drawdown"] == pytest.approx(mdd, rel=1e-9)
    assert result["cumulative_return"] == pytest.approx(wealth - 1.0, rel=1e-9)
    assert result["win_rate"] == pytest.approx(5 / 8)
    assert result["best_day"] == pytest.approx(0.02)
    assert result["worst_day"] == pytest.approx(-0.015)


def test_compute_metrics_insufficient_data_degrades_to_none():
    for returns in ([], [0.01], [None, float("nan")]):
        result = compute_metrics(returns)
        assert result["status"] == "insufficient_data"
        assert result["sharpe"] is None
        assert result["max_drawdown"] is None
        assert result["win_rate"] is None


def test_compute_metrics_flat_series_has_no_sharpe():
    result = compute_metrics([0.001] * 10)
    assert result["status"] == "ok"
    assert result["sharpe"] is None  # volatilidad cero: ratio no definido
    assert result["max_drawdown"] == pytest.approx(0.0)
    assert result["win_rate"] == pytest.approx(1.0)
    assert result["sortino"] is None  # sin dias negativos


def test_exposure_from_snapshot_recomputes_weights():
    snapshot = PortfolioDailySnapshot(
        portfolio_id=1,
        snapshot_date=date(2026, 9, 18),
        base_currency="EUR",
        positions_value_base=Decimal("8000"),
        cash_value_base=Decimal("2000"),
        total_value_base=Decimal("10000"),
    )
    rows = [
        PositionDailySnapshot(
            portfolio_snapshot_id=1,
            portfolio_id=1,
            company_id=i,
            snapshot_date=date(2026, 9, 18),
            quantity=Decimal("1"),
            market_price_native=Decimal("100"),
            currency="EUR",
            market_value_native=Decimal("100"),
            market_value_base=Decimal(value),
            weight=None,  # a proposito: el servicio no depende de esta columna
        )
        for i, value in enumerate(["5000", "2000", "1000"], start=1)
    ]
    exposure = exposure_from_snapshot(snapshot, rows)
    assert exposure["equity_weight"] == pytest.approx(0.8)
    assert exposure["cash_weight"] == pytest.approx(0.2)
    assert exposure["n_positions"] == 3
    assert exposure["top_1_weight"] == pytest.approx(0.5)
    assert exposure["top_5_weight"] == pytest.approx(0.8)


def test_exposure_n_positions_counts_held_rows_even_underwater():
    """Cartera bajo agua (margen > valor): las posiciones siguen existiendo.

    total_value_base negativo apagaba los pesos (correcto: sin NAV positivo
    no hay peso honesto) pero tambien dejaba n_positions en 0 como si no
    hubiera posiciones. El recuento no depende del NAV.
    """
    snapshot = PortfolioDailySnapshot(
        portfolio_id=1,
        snapshot_date=date(2026, 9, 18),
        base_currency="EUR",
        positions_value_base=Decimal("8000"),
        cash_value_base=Decimal("-12000"),
        total_value_base=Decimal("-4000"),
    )
    rows = [
        PositionDailySnapshot(
            portfolio_snapshot_id=1,
            portfolio_id=1,
            company_id=i,
            snapshot_date=date(2026, 9, 18),
            quantity=Decimal("1"),
            market_price_native=Decimal("100"),
            currency="EUR",
            market_value_native=Decimal("100"),
            market_value_base=Decimal(value),
            weight=None,
        )
        for i, value in enumerate(["5000", "3000"], start=1)
    ]
    exposure = exposure_from_snapshot(snapshot, rows)
    assert exposure["n_positions"] == 2
    # Sin NAV positivo, los pesos sobre NAV se quedan en None (no se fabrican).
    assert exposure["top_1_weight"] is None
    assert exposure["equity_weight"] is None


def _seed_portfolio_with_snapshots(db: Session) -> None:
    tenant = Tenant(external_id="tearsheet-test", name="Tearsheet test")
    db.add(tenant)
    db.flush()
    portfolio = Portfolio(
        tenant_id=tenant.id, name="Main", base_currency="EUR", is_default=True
    )
    db.add(portfolio)
    db.flush()
    company = Company(
        ticker="AAA",
        name="AAA",
        exchange="X",
        currency="EUR",
        sector="S",
        industry="I",
        company_type="imported_holding",
        valuation_model="unassigned",
    )
    db.add(company)
    db.flush()
    wealth = 10000.0
    previous_id = None
    for day, r in enumerate(RETURNS, start=1):
        wealth *= 1.0 + r
        snapshot = PortfolioDailySnapshot(
            tenant_id=tenant.id,
            portfolio_id=portfolio.id,
            snapshot_date=date(2026, 9, day),
            base_currency="EUR",
            positions_value_base=Decimal(str(round(wealth * 0.8, 2))),
            cash_value_base=Decimal(str(round(wealth * 0.2, 2))),
            total_value_base=Decimal(str(round(wealth, 2))),
            daily_return=Decimal(str(r)) if day > 1 else None,
        )
        db.add(snapshot)
        db.flush()
        db.add(
            PositionDailySnapshot(
                tenant_id=tenant.id,
                portfolio_snapshot_id=snapshot.id,
                portfolio_id=portfolio.id,
                company_id=company.id,
                snapshot_date=date(2026, 9, day),
                quantity=Decimal("10"),
                market_price_native=Decimal("100"),
                currency="EUR",
                market_value_native=Decimal("1000"),
                market_value_base=snapshot.positions_value_base,
            )
        )
        previous_id = snapshot.id
    db.flush()
    assert previous_id is not None


def test_build_reads_returns_and_exposure_from_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed_portfolio_with_snapshots(db)
        result = TearsheetService().build(db)

    assert result["status"] == "ok"
    # 7 retornos (el primer snapshot no tiene daily_return)
    assert result["metrics"]["n_observations"] == len(RETURNS) - 1
    assert result["metrics"]["sharpe"] is not None
    assert result["metrics"]["max_drawdown"] is not None
    assert result["exposure"]["n_positions"] == 1
    assert result["exposure"]["equity_weight"] == pytest.approx(0.8)
    assert result["trace"]["n_snapshots"] == len(RETURNS)


def test_build_without_portfolio_degrades():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = TearsheetService().build(db)
    assert result["status"] == "no_portfolio"
    assert result["metrics"] is None
    assert result["exposure"] is None


def test_sortino_with_single_negative_period_is_finite():
    """Con un solo periodo negativo la desviacion a la baja (sobre N) existe.

    Retornos [0.02, -0.01, 0.03, 0.01]: media 0.0125;
    DD = sqrt(0.0001 / 4) = 0.005; Sortino (anual 12) = 0.0125/0.005*sqrt(12)
    = 8.660.
    """
    result = compute_metrics([0.02, -0.01, 0.03, 0.01], periods=12, risk_free=0.0)
    assert result["sortino"] == pytest.approx(2.5 * math.sqrt(12), rel=1e-9)


@pytest.mark.parametrize("cash,nav", [("2000", "17000"), ("-5000", "10000"), ("-15000", "0")])
def test_explicit_gross_weights_preserve_nav_contract_and_snapshot(cash, nav):
    snapshot = PortfolioDailySnapshot(
        portfolio_id=1, snapshot_date=date(2026, 9, 18), base_currency="EUR",
        positions_value_base=Decimal("15000"), cash_value_base=Decimal(cash), total_value_base=Decimal(nav),
    )
    rows = [PositionDailySnapshot(
        portfolio_snapshot_id=1, portfolio_id=1, company_id=i, snapshot_date=date(2026, 9, 18),
        quantity=Decimal("1"), market_price_native=Decimal("100"), currency="EUR",
        market_value_native=Decimal(v), market_value_base=Decimal(v), weight=Decimal("0.123"),
    ) for i,v in enumerate(["9000", "6000"], start=1)]
    result = exposure_from_snapshot(snapshot, rows)
    assert result["top_1_gross_positions_weight"] == pytest.approx(0.6)
    assert result["top_5_gross_positions_weight"] == pytest.approx(1.0)
    assert result["gross_positions_value_base"] == 15000
    if Decimal(nav) > 0:
        assert result["top_1_weight"] == pytest.approx(9000 / float(nav))
        assert result["top_5_weight"] == pytest.approx(15000 / float(nav))
        assert result["equity_weight"] + result["cash_weight"] == pytest.approx(1.0)
    else:
        assert result["top_1_weight"] is None
        assert result["top_5_weight"] is None
    assert all(row.weight == Decimal("0.123") for row in rows)



def test_explicit_gross_weights_use_absolute_values_for_long_short_positions():
    snapshot = PortfolioDailySnapshot(
        portfolio_id=1, snapshot_date=date(2026, 9, 18), base_currency="EUR",
        positions_value_base=Decimal("3000"), cash_value_base=Decimal("2000"), total_value_base=Decimal("5000"),
    )
    rows = [PositionDailySnapshot(
        portfolio_snapshot_id=1, portfolio_id=1, company_id=i, snapshot_date=date(2026, 9, 18),
        quantity=Decimal("1"), market_price_native=Decimal("100"), currency="EUR",
        market_value_native=Decimal(v), market_value_base=Decimal(v), weight=Decimal("0.123"),
    ) for i,v in enumerate(["9000", "-6000"], start=1)]
    result = exposure_from_snapshot(snapshot, rows)
    assert result["gross_positions_value_base"] == 15000
    assert result["top_1_gross_positions_weight"] == pytest.approx(0.6)
    assert result["top_5_gross_positions_weight"] == pytest.approx(1.0)
    assert result["top_1_weight"] == pytest.approx(1.8)  # legacy NAV, unchanged
    assert result["top_5_weight"] == pytest.approx(0.6)
    assert all(row.weight == Decimal("0.123") for row in rows)


@pytest.mark.parametrize("unknown", [None, Decimal("NaN"), Decimal("Infinity")])
def test_gross_fields_are_unknown_if_any_position_valuation_is_missing_or_nonfinite(unknown):
    from types import SimpleNamespace

    snapshot = PortfolioDailySnapshot(
        portfolio_id=1, snapshot_date=date(2026, 9, 18), base_currency="EUR",
        positions_value_base=Decimal("9000"), cash_value_base=Decimal("1000"), total_value_base=Decimal("10000"),
    )
    rows = [SimpleNamespace(market_value_base=Decimal("9000")), SimpleNamespace(market_value_base=unknown)]
    result = exposure_from_snapshot(snapshot, rows)
    assert result["gross_positions_value_base"] is None
    assert result["top_1_gross_positions_weight"] is None
    assert result["top_5_gross_positions_weight"] is None
    assert result["top_1_weight"] == pytest.approx(0.9)  # NAV contract unchanged



def _seed_returns(db: Session, returns: list[float | None]) -> None:
    """Snapshots diarios con ``daily_return`` dado (None = serie rota/base)."""
    tenant = Tenant(external_id="tearsheet-gap", name="Tearsheet gap")
    db.add(tenant)
    db.flush()
    portfolio = Portfolio(tenant_id=tenant.id, name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    db.flush()
    for day, r in enumerate(returns, start=1):
        db.add(
            PortfolioDailySnapshot(
                tenant_id=tenant.id,
                portfolio_id=portfolio.id,
                snapshot_date=date(2026, 9, day),
                base_currency="EUR",
                positions_value_base=Decimal("1000"),
                cash_value_base=Decimal("0"),
                total_value_base=Decimal("1000"),
                daily_return=Decimal(str(r)) if r is not None else None,
            )
        )
    db.flush()


def test_build_does_not_splice_return_segments_across_a_gap():
    """Auditoria A: un hueco (daily_return=None tras la base) rompe la serie.

    Antes se descartaban los None y se encadenaban +50 % y -40 % de dos
    tramos distintos como si fueran dias consecutivos (rentabilidad -10 %
    sobre un periodo que nadie midio). Solo se usa el tramo continuo mas
    reciente y la API dice que la serie tiene huecos.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed_returns(db, [None, 0.5, None, -0.4, 0.1])
        result = TearsheetService().build(db)

    metrics = result["metrics"]
    assert metrics["n_observations"] == 2
    assert metrics["cumulative_return"] == pytest.approx(0.6 * 1.1 - 1.0)
    assert result["qualification"]["continuous"] is False
    assert result["qualification"]["series_breaks"] == 1
    assert result["qualification"]["excluded_returns"] == 1
    assert result["qualification"]["start_date"] == "2026-09-03"
    assert result["qualification"]["end_date"] == "2026-09-05"
    assert result["trace"]["n_returns"] == 2


def test_build_without_gaps_is_qualified_as_continuous():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed_returns(db, [None, 0.01, -0.02, 0.03])
        result = TearsheetService().build(db)
    assert result["metrics"]["n_observations"] == 3
    assert result["qualification"] == {
        "continuous": True,
        "series_breaks": 0,
        "excluded_returns": 0,
        "start_date": "2026-09-01",
        "end_date": "2026-09-04",
    }


def test_build_gap_leaving_one_return_is_insufficient_not_spliced():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed_returns(db, [None, 0.02, 0.03, None, 0.01])
        result = TearsheetService().build(db)
    assert result["status"] == "insufficient_data"
    assert result["metrics"]["n_observations"] == 1
    assert result["qualification"]["excluded_returns"] == 2



def test_margin_exposure_labels_equity_weight_as_leverage_and_keeps_cash_sign():
    """Auditoria A: posiciones 100, caja -25, NAV 75. equity_weight (1.333) es
    apalancamiento, no distribucion: la API lo dice y da la caja con signo."""
    snap = PortfolioDailySnapshot(
        snapshot_date=date(2026, 9, 1), base_currency="EUR",
        positions_value_base=Decimal("100"), cash_value_base=Decimal("-25"),
        total_value_base=Decimal("75"),
    )
    row = PositionDailySnapshot(
        snapshot_date=date(2026, 9, 1), quantity=Decimal("1"), market_price_native=Decimal("100"),
        currency="EUR", market_value_native=Decimal("100"), market_value_base=Decimal("100"),
    )
    result = exposure_from_snapshot(snap, [row])
    assert result["equity_weight"] == pytest.approx(100 / 75)
    assert result["net_leverage"] == pytest.approx(100 / 75)
    assert result["gross_leverage"] == pytest.approx(100 / 75)
    assert result["weight_bases"]["equity_weight"] == "leverage_positions_over_nav"
    assert result["weight_bases"]["top_1_gross_positions_weight"] == "gross_positions_abs"
    assert result["cash_value_base"] == pytest.approx(-25.0)
    assert result["positions_value_base"] == pytest.approx(100.0)
    assert result["top_1_gross_positions_weight"] == pytest.approx(1.0)
