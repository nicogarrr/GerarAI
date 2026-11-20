"""SQLite round trips the real ingest/snapshot/read path, not hand-built JSON."""
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, MarketObservation
from app.services.market_observation_service import store_series
from app.services.market_snapshot_service import build_snapshot, latest_snapshot
from app.services.vix_context import vix_context


@pytest.mark.parametrize('offset_hours', [0, 3, -5])
def test_ingest_to_context_utc_normalized_before_sqlite_drops_offset(offset_hours):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    now = datetime.now(UTC) - timedelta(seconds=1)
    supplied = now.astimezone(timezone(timedelta(hours=offset_hours)))
    try:
        with sessionmaker(engine)() as db:
            store_series(db, 'vix_us', [{'date': now.date().isoformat(), 'value': '31'}], supplied)
            db.commit()
            db.expire_all()
            row = db.query(MarketObservation).one()
            # SQLite stores UTC wall time, not the caller's non-UTC wall time.
            assert row.fetched_at == now.replace(tzinfo=None)
            snapshot = build_snapshot(db, now.date(), now + timedelta(seconds=1))
            assert datetime.fromisoformat(snapshot.metrics['vix_us']['fetched_at']) == now
            payload = latest_snapshot(db)
            assert payload['vix_context']['status'] == 'available'
            assert payload['vix_context']['band'] == 'high'
            assert payload['vix_context']['value'] == 31
            assert payload['vix_context']['date'] == now.date().isoformat()
    finally:
        engine.dispose()


def test_external_naive_timestamp_is_still_invalid():
    now = datetime.now(UTC)
    metric = {'value': 31, 'date': now.date().isoformat(),
              'fetched_at': now.replace(tzinfo=None).isoformat(), 'source': 'FRED',
              'source_url': 'https://fred.stlouisfed.org/series/VIXCLS', 'unit': 'índice'}
    assert vix_context(metric, now)['reason'] == 'invalid'
