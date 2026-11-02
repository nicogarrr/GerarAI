"""Plan de aportaciones ponderado por nivel DCA.

«Este mes X EUR a POOL, Y EUR a UBER»: la cuota mensual se reparte entre los
tickers del plan (objetivos por ticker o, sin ellos, posiciones vivas a partes
iguales) multiplicando cada peso por el cuadrado del nivel DCA del motor (4X pesa 16,
3X 9, 2X 4, 1X 1, recorte pesa 0). Degrada limpio: sin tabla dca_signal_states o sin nivel
para un ticker, ese ticker pesa como 1X y se dice.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Position
from app.models.entities import Base
from app.services.investment_plan_service import InvestmentPlanService
from app.services.plan_contribution_split import (
    SplitCandidate,
    build_contribution_split,
    split_contribution,
)

TENANT = "tenant-test"


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    """Reloj fijo: los niveles de prueba son de 2026-10 y no deben caducar con el calendario."""
    from app.services import plan_contribution_split as split_module

    monkeypatch.setattr(split_module, "_today", lambda: date(2026, 10, 30))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = TENANT
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NYSE",
        currency="USD",
        sector="Tech",
        industry="Tech",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _plan(db: Session, targets: list[dict], amount: str = "300") -> None:
    InvestmentPlanService().upsert_plan(
        db,
        monthly_contribution=Decimal(amount),
        monthly_contribution_currency="EUR",
        start_date=date(2026, 1, 1),
        horizon_years=30,
        target_allocations=targets,
    )


def _dca_table(db: Session, rows: list[tuple[str, int | None, int]]) -> None:
    for symbol, company_id, level in rows:
        db.add(_real_dca_row(tenant=TENANT, symbol=symbol, level=level, company_id=company_id))
    db.commit()


def _cand(ticker: str, weight: str, level: int | None) -> SplitCandidate:
    return SplitCandidate(ticker=ticker, base_weight=Decimal(weight), dca_level=level)


def test_pure_split_weights_by_dca_level():
    # 3X pesa 9 y 1X pesa 1: 9/10 y 1/10 de los 300.
    result = split_contribution(Decimal("300"), [_cand("POOL", "50", 3), _cand("UBER", "50", 1)])
    amounts = {row["ticker"]: row["amount"] for row in result["allocations"]}
    assert amounts == {"POOL": 270.0, "UBER": 30.0}
    assert result["unallocated"] == 0.0


def test_weight_is_the_square_of_the_dca_level():
    """Peso nivel² (1X→1, 2X→4, 3X→9, 4X→16): backtest gerarai-dcaplano, +1,3 puntos de TIR fuera de muestra."""
    result = split_contribution(
        Decimal("300"), [_cand(t, "1", level) for t, level in (("A", 4), ("B", 3), ("C", 2), ("D", 1))]
    )
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert {t: rows[t]["multiplier"] for t in "ABCD"} == {"A": 16, "B": 9, "C": 4, "D": 1}
    assert rows["A"]["reason"] == "4X DCA: peso ×16"
    assert rows["D"]["reason"] == "1X DCA: peso ×1"
    # 16 : 9 : 4 : 1 sobre 30 partes de 300 -> 160 / 90 / 40 / 10.
    assert {t: rows[t]["amount"] for t in "ABCD"} == {"A": 160.0, "B": 90.0, "C": 40.0, "D": 10.0}


@pytest.mark.parametrize(
    "levels",
    [
        (4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
        (4, 3, 2, 1, -1, -2, None),
        (2, 2, 3),
        (1, 1, 1),
        (4, -1),
    ],
)
@pytest.mark.parametrize("amount", ["300", "1000", "123.45", "0.07"])
def test_monthly_budget_is_unchanged_only_the_split_moves(levels, amount):
    """Mismo dinero total al mes que antes: el cuadrado solo cambia el reparto, nunca la cuota."""
    candidates = [_cand(f"T{i}", "1", level) for i, level in enumerate(levels)]
    result = split_contribution(Decimal(amount), candidates)
    spent = sum(Decimal(str(row["amount"])) for row in result["allocations"])
    assert spent == Decimal(amount)
    assert result["unallocated"] == 0.0
    assert result["status"] == "ok"


def test_trim_level_gets_nothing_and_missing_level_is_1x():
    result = split_contribution(
        Decimal("100"), [_cand("POOL", "1", 2), _cand("UBER", "1", -1), _cand("MSFT", "1", None)]
    )
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert rows["UBER"]["amount"] == 0.0
    assert rows["UBER"]["multiplier"] == 0
    assert rows["MSFT"]["multiplier"] == 1
    assert "sin nivel DCA" in rows["MSFT"]["reason"]
    # 2X pesa 4: 4 : 0 : 1 -> 80 / 0 / 20 y la suma cuadra al centimo.
    assert rows["POOL"]["multiplier"] == 4
    assert rows["POOL"]["amount"] == 80.0
    assert rows["MSFT"]["amount"] == 20.0
    assert sum(row["amount"] for row in result["allocations"]) == 100.0


def test_everything_in_trim_keeps_the_money_unallocated():
    result = split_contribution(Decimal("300"), [_cand("POOL", "1", -2), _cand("UBER", "1", -1)])
    assert result["status"] == "all_trim"
    assert result["unallocated"] == 300.0
    assert all(row["amount"] == 0.0 for row in result["allocations"])


def test_rounding_residual_goes_to_largest():
    result = split_contribution(Decimal("100"), [_cand(t, "1", 1) for t in ("A", "B", "C")])
    assert sorted(row["amount"] for row in result["allocations"]) == [33.33, 33.33, 33.34]


def test_no_plan(db):
    assert build_contribution_split(db) == {"plan_exists": False}


def test_targets_without_dca_table_degrade_to_target_weights(db):
    _company(db, "POOL")
    _company(db, "UBER")
    _plan(
        db,
        [
            {"kind": "ticker", "label": "POOL", "target_pct": 20, "band_pct": 5},
            {"kind": "ticker", "label": "UBER", "target_pct": 10, "band_pct": 5},
            {"kind": "sector", "label": "Tech", "target_pct": 50, "band_pct": 5},
        ],
    )
    _drop_dca_table(db)
    result = build_contribution_split(db)
    assert result["dca_available"] is False
    assert result["basis"] == "objetivos_ticker"
    amounts = {row["ticker"]: row["amount"] for row in result["allocations"]}
    assert amounts == {"POOL": 200.0, "UBER": 100.0}
    assert any("motor DCA" in note for note in result["notes"])
    assert result["summary"].startswith("Este mes")


def test_targets_weighted_by_dca_levels(db):
    pool = _company(db, "POOL")
    _company(db, "UBER")
    _plan(
        db,
        [
            {"kind": "ticker", "label": "POOL", "target_pct": 50, "band_pct": 5},
            {"kind": "ticker", "label": "UBER", "target_pct": 50, "band_pct": 5},
        ],
    )
    # POOL por company_id, UBER por simbolo.
    _dca_table(db, [("POOL", pool.id, 3), ("UBER", None, 1)])
    result = build_contribution_split(db)
    assert result["dca_available"] is True
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert rows["POOL"]["amount"] == 270.0
    assert rows["POOL"]["dca_label"] == "3X DCA"
    assert rows["UBER"]["amount"] == 30.0
    assert result["currency"] == "EUR"
    assert "270,00 EUR a POOL" in result["summary"]


def test_other_tenant_dca_rows_are_ignored(db):
    pool = _company(db, "POOL")
    _plan(db, [{"kind": "ticker", "label": "POOL", "target_pct": 100, "band_pct": 5}])
    _dca_table(db, [])
    _other_tenant_dca_row(db, tenant="otro", symbol="POOL", level=4, company_id=pool.id)
    db.commit()
    row = build_contribution_split(db)["allocations"][0]
    assert row["dca_level"] is None
    assert row["multiplier"] == 1


def test_without_ticker_targets_uses_live_positions_equally(db):
    pool = _company(db, "POOL")
    uber = _company(db, "UBER")
    gone = _company(db, "GONE")
    _plan(db, [{"kind": "sector", "label": "Tech", "target_pct": 50, "band_pct": 5}])
    for company, qty in ((pool, "10"), (uber, "5"), (gone, "0")):
        db.add(Position(company_id=company.id, quantity=Decimal(qty), currency="USD"))
    db.commit()
    _dca_table(db, [("POOL", pool.id, 2)])
    result = build_contribution_split(db)
    assert result["basis"] == "posiciones_iguales"
    rows = {row["ticker"]: row["amount"] for row in result["allocations"]}
    # POOL 2X pesa 4 frente al 1 de UBER (sin nivel).
    assert rows == {"POOL": 240.0, "UBER": 60.0}


def test_no_candidates_says_so(db):
    _plan(db, [])
    result = build_contribution_split(db)
    assert result["status"] == "no_candidates"
    assert result["allocations"] == []
    assert result["summary"] is None


def test_route_returns_split(db):
    from app.api.routes.plan import contribution_split

    _company(db, "POOL")
    _plan(db, [{"kind": "ticker", "label": "POOL", "target_pct": 100, "band_pct": 5}])
    assert contribution_split(db)["allocations"][0]["amount"] == 300.0


def _real_dca_row(*, tenant, symbol, level, company_id=None, status="forming",
                  period="2026-10", day=None, close="100"):
    """Fila del modelo real (#2310): la tabla ya la crea Base.metadata."""
    from datetime import date as _d
    from decimal import Decimal as _D

    from app.models.entities import DcaSignalState

    return DcaSignalState(
        tenant_id=tenant, symbol=symbol, company_id=company_id, level=level, status=status,
        period=period, signal_date=day or _d(2026, 10, 24), close=_D(close), currency="USD",
        metrics={}, level_prices={}, sources=[], params_version="nico-v1", data_source="test",
    )


def _drop_dca_table(db) -> None:
    """Simula «motor DCA no desplegado»: sin la tabla real."""
    from app.models.entities import DcaSignalState

    DcaSignalState.__table__.drop(db.get_bind())


def _other_tenant_dca_row(db, *, tenant, symbol, level, company_id=None, status="closed"):
    """Fila de OTRO tenant: el ORM bloquea escrituras cruzadas, se inserta en SQL."""
    from sqlalchemy import text as _text

    db.execute(_text(
        "INSERT INTO dca_signal_states (tenant_id, symbol, company_id, level, status, period, signal_date,"
        " close, metrics, level_prices, sources, params_version, evaluated_at, data_source, created_at,"
        " updated_at) VALUES (:t, :s, :c, :l, :st, '2026-09', '2026-09-30', 100, '{}', '{}', '[]',"
        " 'nico-v1', '2026-09-30', 'test', '2026-09-30', '2026-09-30')"
    ), {"t": tenant, "s": symbol, "c": company_id, "l": level, "st": status})


def test_dca_split_exposes_same_savings_contract(db):
    _plan(db, [], amount="1000")
    result = build_contribution_split(db)
    projection = result['savings_projection']
    assert projection['monthly_contribution'] == result['amount'] == 1000
    assert projection['currency'] == result['currency'] == 'EUR'
    assert projection['scenarios'][2]['annual_total_return'] == .05
    assert projection['portfolio_included'] is False


def test_stale_dca_level_does_not_drive_this_months_split(db):
    """Un 4X de hace meses (ticker que dejo de evaluarse) no puede repartir el dinero de hoy."""
    pool = _company(db, "POOL")
    uber = _company(db, "UBER")
    _plan(
        db,
        [
            {"kind": "ticker", "label": "POOL", "target_pct": 50, "band_pct": 5},
            {"kind": "ticker", "label": "UBER", "target_pct": 50, "band_pct": 5},
        ],
    )
    db.add(_real_dca_row(tenant=TENANT, symbol="POOL", level=4, company_id=pool.id,
                         status="confirmed", period="2026-03"))
    db.add(_real_dca_row(tenant=TENANT, symbol="UBER", level=1, company_id=uber.id,
                         status="confirmed", period="2026-09"))
    db.commit()
    result = build_contribution_split(db)
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert rows["POOL"]["amount"] == 150.0 and rows["UBER"]["amount"] == 150.0
    assert rows["POOL"]["dca_stale"] is True and rows["POOL"]["multiplier"] == 1
    assert rows["POOL"]["dca_level"] is None and rows["POOL"]["dca_period"] == "2026-03"
    assert "caducado" in rows["POOL"]["reason"]
    assert rows["UBER"]["dca_stale"] is False and rows["UBER"]["dca_label"] == "1X DCA"
    assert any("POOL" in note and "más de un mes" in note for note in result["notes"])


def test_future_dca_period_is_suspect_and_does_not_drive_this_months_split(db):
    """Un nivel con periodo EN EL FUTURO (dato corrupto, no evaluable hoy) no reparte dinero."""
    pool = _company(db, "POOL")
    uber = _company(db, "UBER")
    _plan(
        db,
        [
            {"kind": "ticker", "label": "POOL", "target_pct": 50, "band_pct": 5},
            {"kind": "ticker", "label": "UBER", "target_pct": 50, "band_pct": 5},
        ],
    )
    db.add(_real_dca_row(tenant=TENANT, symbol="POOL", level=4, company_id=pool.id,
                         status="confirmed", period="2026-12"))
    db.add(_real_dca_row(tenant=TENANT, symbol="UBER", level=1, company_id=uber.id,
                         status="confirmed", period="2026-09"))
    db.commit()
    result = build_contribution_split(db)
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert rows["POOL"]["dca_stale"] is True and rows["POOL"]["multiplier"] == 1
    assert rows["POOL"]["dca_level"] is None and rows["POOL"]["dca_period"] == "2026-12"
    assert rows["POOL"]["amount"] == 150.0 and rows["UBER"]["amount"] == 150.0


def test_stale_trim_level_does_not_freeze_the_contribution(db):
    pool = _company(db, "POOL")
    _plan(db, [{"kind": "ticker", "label": "POOL", "target_pct": 100, "band_pct": 5}])
    db.add(_real_dca_row(tenant=TENANT, symbol="POOL", level=-2, company_id=pool.id,
                         status="confirmed", period="2025-12"))
    db.commit()
    result = build_contribution_split(db)
    assert result["status"] == "ok"
    assert result["allocations"][0]["amount"] == 300.0


# --- Tope de concentración: sin aportación nueva a lo que ya pesa más del doble de su peso base ---


def _capped(ticker: str, weight: str, level: int | None, share: str, base: str) -> SplitCandidate:
    return SplitCandidate(
        ticker=ticker,
        base_weight=Decimal(weight),
        dca_level=level,
        concentration_capped=True,
        market_share_pct=Decimal(share),
        base_share_pct=Decimal(base),
    )


def test_capped_holding_gets_nothing_and_the_budget_goes_to_the_rest():
    result = split_contribution(
        Decimal("300"), [_capped("POOL", "1", 4, "80", "33.3"), _cand("UBER", "1", 1), _cand("MSFT", "1", 2)]
    )
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert rows["POOL"]["amount"] == 0.0
    assert rows["POOL"]["multiplier"] == 16  # el nivel no cambia; solo el tope lo deja fuera este mes
    assert rows["POOL"]["concentration_capped"] is True
    assert rows["POOL"]["market_share_pct"] == 80.0 and rows["POOL"]["base_share_pct"] == 33.3
    assert rows["POOL"]["reason"] == (
        "4X DCA: ya pesa el 80,0 % del plan, más del doble de su peso objetivo (33,3 %); "
        "este mes no recibe aportación"
    )
    # 1X pesa 1 y 2X pesa 4: 60 / 240, y la cuota del mes no cambia.
    assert rows["UBER"]["amount"] == 60.0 and rows["MSFT"]["amount"] == 240.0
    assert rows["UBER"]["concentration_capped"] is False
    assert result["unallocated"] == 0.0


def test_cap_never_leaves_the_month_without_a_destination():
    """Si el tope dejaría todo a cero (el resto está en recorte), se ignora: la cuota se aporta igual."""
    result = split_contribution(Decimal("300"), [_capped("POOL", "1", 2, "90", "50"), _cand("UBER", "1", -1)])
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert result["status"] == "ok"
    assert rows["POOL"]["amount"] == 300.0
    assert rows["POOL"]["concentration_capped"] is False
    assert rows["POOL"]["reason"] == "2X DCA: peso ×4"


def _position(db: Session, company: Company, qty: str, value_base: str | None, base: str = "EUR") -> None:
    db.add(
        Position(
            company_id=company.id,
            quantity=Decimal(qty),
            currency="USD",
            base_currency=base,
            market_value_base=None if value_base is None else Decimal(value_base),
        )
    )


def test_build_caps_a_holding_over_twice_its_equal_weight(db):
    pool, uber, msft = (_company(db, t) for t in ("POOL", "UBER", "MSFT"))
    _plan(db, [{"kind": "sector", "label": "Tech", "target_pct": 50, "band_pct": 5}])
    # Peso base 1/3 cada una; POOL ya es el 80 % (> 2 × 33,3 %).
    for company, value in ((pool, "800"), (uber, "100"), (msft, "100")):
        _position(db, company, "1", value)
    db.commit()
    _dca_table(db, [("POOL", pool.id, 4), ("UBER", uber.id, 1), ("MSFT", msft.id, 2)])
    result = build_contribution_split(db)
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert rows["POOL"]["amount"] == 0.0 and rows["POOL"]["concentration_capped"] is True
    assert rows["UBER"]["amount"] == 60.0 and rows["MSFT"]["amount"] == 240.0
    assert sum(row["amount"] for row in result["allocations"]) == 300.0
    assert (
        "Sin aportación nueva este mes a POOL: ya pesa más del doble de su peso objetivo en el plan."
        in result["notes"]
    )


def test_build_uses_ticker_targets_as_base_weight_and_sums_portfolios(db):
    pool, uber = _company(db, "POOL"), _company(db, "UBER")
    _plan(
        db,
        [
            {"kind": "ticker", "label": "POOL", "target_pct": 20, "band_pct": 5},
            {"kind": "ticker", "label": "UBER", "target_pct": 80, "band_pct": 5},
        ],
    )
    # POOL en dos carteras: 300 + 200 = 500 de 1.000 = 50 % > 2 × 20 %.
    _position(db, pool, "1", "300")
    _position(db, pool, "1", "200")
    _position(db, uber, "1", "500")
    db.commit()
    _dca_table(db, [("POOL", pool.id, 1), ("UBER", uber.id, 1)])
    rows = {row["ticker"]: row for row in build_contribution_split(db)["allocations"]}
    assert rows["POOL"]["concentration_capped"] is True and rows["POOL"]["amount"] == 0.0
    assert rows["POOL"]["market_share_pct"] == 50.0 and rows["POOL"]["base_share_pct"] == 20.0
    assert rows["UBER"]["amount"] == 300.0


def test_build_at_exactly_twice_is_not_capped_and_plan_tickers_without_position_count_zero(db):
    pool, uber, msft = (_company(db, t) for t in ("POOL", "UBER", "MSFT"))
    _plan(
        db,
        [
            {"kind": "ticker", "label": t, "target_pct": 25, "band_pct": 5}
            for t in ("POOL", "UBER", "MSFT", "NVDA")
        ],
    )
    # POOL 50 % = 2 × 25 %: justo en el límite, no se topa. NVDA sin posición ni empresa: valor 0.
    _position(db, pool, "1", "500")
    _position(db, uber, "1", "250")
    _position(db, msft, "1", "250")
    db.commit()
    rows = {row["ticker"]: row for row in build_contribution_split(db)["allocations"]}
    assert not any(row["concentration_capped"] for row in rows.values())
    assert rows["POOL"]["market_share_pct"] == 50.0
    assert rows["NVDA"]["market_share_pct"] == 0.0
    assert all(row["amount"] == 75.0 for row in rows.values())


@pytest.mark.parametrize(
    "values",
    [
        ("800", None, "100"),  # una posición viva sin valor de mercado: no se sabe cuánto pesa
        ("800", "0", "100"),  # valor 0 con cantidad > 0 = sin precio
    ],
)
def test_build_without_reliable_market_values_does_not_cap(db, values):
    companies = [_company(db, t) for t in ("POOL", "UBER", "MSFT")]
    _plan(db, [{"kind": "sector", "label": "Tech", "target_pct": 50, "band_pct": 5}])
    for company, value in zip(companies, values, strict=True):
        _position(db, company, "1", value)
    db.commit()
    rows = build_contribution_split(db)["allocations"]
    assert not any(row["concentration_capped"] for row in rows)
    assert all(row["market_share_pct"] is None for row in rows)
    assert sorted(row["amount"] for row in rows) == [100.0, 100.0, 100.0]


def test_build_with_mixed_base_currencies_does_not_cap(db):
    pool, uber, msft = (_company(db, t) for t in ("POOL", "UBER", "MSFT"))
    _plan(db, [{"kind": "sector", "label": "Tech", "target_pct": 50, "band_pct": 5}])
    _position(db, pool, "1", "800", base="USD")
    _position(db, uber, "1", "100")
    _position(db, msft, "1", "100")
    db.commit()
    rows = build_contribution_split(db)["allocations"]
    assert not any(row["concentration_capped"] for row in rows)


def test_other_tenant_positions_do_not_count_for_the_cap(db):
    from sqlalchemy import text as _text

    pool, uber, msft = (_company(db, t) for t in ("POOL", "UBER", "MSFT"))
    _plan(db, [{"kind": "sector", "label": "Tech", "target_pct": 50, "band_pct": 5}])
    for company in (pool, uber, msft):
        _position(db, company, "1", "100")
    db.commit()
    # Otro usuario con 10.000 en POOL: no puede topar el plan de este.
    db.execute(_text(
        "INSERT INTO positions (tenant_id, company_id, quantity, average_cost, market_price, market_value,"
        " unrealized_pnl, realized_pnl, currency, base_currency, market_value_base, source, as_of, created_at,"
        " updated_at) VALUES ('otro', :c, 1, 0, 0, 0, 0, 0, 'USD', 'EUR', 10000, 'manual', '2026-10-01',"
        " '2026-10-01', '2026-10-01')"
    ), {"c": pool.id})
    db.commit()
    rows = {row["ticker"]: row for row in build_contribution_split(db)["allocations"]}
    assert rows["POOL"]["concentration_capped"] is False
    assert rows["POOL"]["market_share_pct"] == 33.3
    assert rows["POOL"]["amount"] == 100.0
