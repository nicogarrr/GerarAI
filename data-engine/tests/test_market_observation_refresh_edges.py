"""FRED refresh records source failures and continues with other series."""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import MarketObservation
from app.models.entities import Base
from app.services import market_observation_service as service


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def test_store_rejects_unknown_series_or_naive_time_and_skips_future_rows(db):
    with pytest.raises(ValueError, match="Serie u hora"):
        service.store_series(db, "unknown", [], datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="Serie u hora"):
        service.store_series(db, "treasury_10y_us", [], datetime(2026, 1, 1))
    result = service.store_series(
        db, "treasury_10y_us", [{"date": "2026-01-02", "value": "3.5"}], datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert result == {"added": 0, "revisions_applied": 0}
    assert list(db.scalars(select(MarketObservation))) == []


def test_refresh_empty_failure_rollback_and_next_success(db):
    calls = []

    class Client:
        async def series_csv(self, series_id, *, limit):
            calls.append(series_id)
            assert limit == 800
            if series_id == "MORTGAGE30US":
                return {"observations": []}
            if series_id == "DGS10":
                # Flush a partial row before failing; refresh must roll it back.
                service.store_series(
                    db,
                    "treasury_10y_us",
                    [{"date": "2026-01-01", "value": "4"}],
                    datetime(2026, 1, 2, tzinfo=UTC),
                )
                raise httpx.ReadTimeout("upstream private detail")
            return {"observations": [{"date": "2026-01-01", "value": "2.5"}]}

    result = asyncio.run(service.refresh_fred(db, client=Client()))
    assert calls == [spec[0] for spec in service.FRED_SERIES.values()]
    assert result["errors"] == {"mortgage_30y_us": "sin datos", "treasury_10y_us": "ReadTimeout"}
    assert set(result["series"]) == set(service.FRED_SERIES) - set(result["errors"])
    assert all(outcome == {"added": 1, "revisions_applied": 0} for outcome in result["series"].values())
    rows = list(db.scalars(select(MarketObservation)))
    assert {row.metric_key for row in rows} == set(result["series"])
    assert all(float(row.value) == 2.5 and row.source == "FRED" for row in rows)
