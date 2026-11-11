"""Hermetic FRED ingestion: invalid inputs, source isolation and immutable vintages."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import MarketObservation
from app.models.entities import Base
from app.services.market_observation_service import parse_points, store_series

DAY = date(2026, 1, 1)
FETCHED = datetime(2026, 1, 2, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def observation(**changes):
    values = dict(
        metric_key="vix_us",
        geography="US",
        observation_date=DAY,
        value=Decimal("20"),
        unit="índice",
        source="FRED",
        source_url="https://fred.stlouisfed.org/series/VIXCLS",
        fetched_at=FETCHED - timedelta(days=1),
        vintage="initial",
        status="observed",
    )
    values.update(changes)
    return MarketObservation(**values)


def test_parser_rejects_invalid_values_sorts_and_keeps_last_valid_duplicate():
    rows = [
        {},
        {"date": "bad", "value": "3"},
        {"date": None, "value": "3"},
        {"date": "2026-01-01", "value": "."},
        {"date": "2026-01-01", "value": "NaN"},
        {"date": "2026-01-01", "value": "Infinity"},
        {"date": "2026-01-01", "value": "-Infinity"},
        {"date": "2026-01-02", "value": "0"},
        {"date": "2026-01-01", "value": "-1.25"},
        {"date": "2026-01-01", "value": "2.50"},
        {"date": "2026-01-01", "value": "NaN"},
    ]
    assert parse_points(rows) == [(DAY, Decimal("2.50")), (date(2026, 1, 2), Decimal("0"))]


@pytest.mark.parametrize(
    "foreign",
    [
        {"metric_key": "treasury_10y_us"},
        {"geography": "CA"},
        {"source": "OTHER"},
        {"status": "rejected"},
    ],
)
def test_latest_lookup_ignores_other_series_country_source_or_status(db, foreign):
    original = observation()
    unrelated = observation(**foreign, value=Decimal("99"), vintage="foreign", fetched_at=FETCHED)
    db.add_all([original, unrelated])
    db.flush()
    result = store_series(db, "vix_us", [{"date": DAY.isoformat(), "value": "20"}], FETCHED)
    assert result == {"added": 0, "revisions_applied": 0}
    assert list(db.scalars(select(MarketObservation).order_by(MarketObservation.id))) == [original, unrelated]
    assert original.value == Decimal("20") and unrelated.value == Decimal("99")


def test_equal_timestamps_use_newest_id_and_append_without_changing_old_rows(db):
    first = observation()
    second = observation(value=Decimal("21"), vintage="revision")
    db.add_all([first, second])
    db.flush()
    assert first.id < second.id
    rows = [{"date": DAY.isoformat(), "value": "21"}]
    assert store_series(db, "vix_us", rows, FETCHED) == {"added": 0, "revisions_applied": 0}
    rows[0]["value"] = "22"
    assert store_series(db, "vix_us", rows, FETCHED) == {"added": 1, "revisions_applied": 1}
    db.refresh(first)
    db.refresh(second)
    assert (first.value, second.value) == (Decimal("20"), Decimal("21"))
    saved = list(db.scalars(select(MarketObservation).order_by(MarketObservation.id)))
    assert len(saved) == 3 and saved[-1].value == Decimal("22")
    assert saved[-1].vintage not in {"initial", "revision"}
    assert store_series(db, "vix_us", rows, FETCHED) == {"added": 0, "revisions_applied": 0}


def test_existing_initial_vintage_is_not_overwritten_when_not_observed(db):
    rejected = observation(status="rejected")
    db.add(rejected)
    db.flush()
    assert store_series(db, "vix_us", [{"date": DAY.isoformat(), "value": "25"}], FETCHED) == {
        "added": 0,
        "revisions_applied": 0,
    }
    db.refresh(rejected)
    assert rejected.status == "rejected" and rejected.value == Decimal("20")
    assert list(db.scalars(select(MarketObservation))) == [rejected]


def test_future_cutoff_is_utc_and_includes_today(db):
    # Local Jan 2 is still Jan 1 UTC; Jan 2 observations must stay out.
    local = datetime(2026, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    result = store_series(
        db,
        "vix_us",
        [
            {"date": "2026-01-01", "value": "0"},
            {"date": "2026-01-02", "value": "22"},
        ],
        local,
    )
    assert result == {"added": 1, "revisions_applied": 0}
    saved = list(db.scalars(select(MarketObservation)))
    assert len(saved) == 1 and saved[0].observation_date == DAY
    assert saved[0].value == Decimal("0")
    assert saved[0].source_url == "https://fred.stlouisfed.org/series/VIXCLS"
