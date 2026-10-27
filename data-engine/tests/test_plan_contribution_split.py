"""Plan de aportaciones ponderado por nivel DCA.

«Este mes X EUR a POOL, Y EUR a UBER»: la cuota mensual se reparte entre los
tickers del plan (objetivos por ticker o, sin ellos, posiciones vivas a partes
iguales) multiplicando cada peso por el nivel DCA del motor (4X pesa 4, 1X pesa
1, recorte pesa 0). Degrada limpio: sin tabla dca_signal_states o sin nivel
para un ticker, ese ticker pesa como 1X y se dice.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
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
    db.execute(
        text(
            "CREATE TABLE dca_signal_states (id INTEGER PRIMARY KEY, tenant_id VARCHAR, symbol VARCHAR,"
            " company_id INTEGER, level INTEGER, status VARCHAR, period VARCHAR, signal_date DATE)"
        )
    )
    for index, (symbol, company_id, level) in enumerate(rows, start=1):
        db.execute(
            text(
                "INSERT INTO dca_signal_states VALUES (:i, :t, :s, :c, :l, 'forming', '2026-10', '2026-10-24')"
            ),
            {"i": index, "t": TENANT, "s": symbol, "c": company_id, "l": level},
        )
    db.commit()


def _cand(ticker: str, weight: str, level: int | None) -> SplitCandidate:
    return SplitCandidate(ticker=ticker, base_weight=Decimal(weight), dca_level=level)


def test_pure_split_weights_by_dca_level():
    result = split_contribution(Decimal("300"), [_cand("POOL", "50", 3), _cand("UBER", "50", 1)])
    amounts = {row["ticker"]: row["amount"] for row in result["allocations"]}
    assert amounts == {"POOL": 225.0, "UBER": 75.0}
    assert result["unallocated"] == 0.0


def test_trim_level_gets_nothing_and_missing_level_is_1x():
    result = split_contribution(
        Decimal("100"), [_cand("POOL", "1", 2), _cand("UBER", "1", -1), _cand("MSFT", "1", None)]
    )
    rows = {row["ticker"]: row for row in result["allocations"]}
    assert rows["UBER"]["amount"] == 0.0
    assert rows["UBER"]["multiplier"] == 0
    assert rows["MSFT"]["multiplier"] == 1
    assert "sin nivel DCA" in rows["MSFT"]["reason"]
    # 2 : 0 : 1 -> 66,67 / 0 / 33,33 y la suma cuadra al centimo.
    assert rows["POOL"]["amount"] == 66.67
    assert rows["MSFT"]["amount"] == 33.33
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
    assert rows["POOL"]["amount"] == 225.0
    assert rows["POOL"]["dca_label"] == "3X DCA"
    assert rows["UBER"]["amount"] == 75.0
    assert result["currency"] == "EUR"
    assert "225,00 EUR a POOL" in result["summary"]


def test_other_tenant_dca_rows_are_ignored(db):
    pool = _company(db, "POOL")
    _plan(db, [{"kind": "ticker", "label": "POOL", "target_pct": 100, "band_pct": 5}])
    _dca_table(db, [])
    db.execute(
        text(
            "INSERT INTO dca_signal_states VALUES (99, 'otro', 'POOL', :c, 4, 'closed', '2026-09', '2026-09-30')"
        ),
        {"c": pool.id},
    )
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
    assert rows == {"POOL": 200.0, "UBER": 100.0}


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
