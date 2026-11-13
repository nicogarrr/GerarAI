"""A future stored macro snapshot cannot masquerade as available today."""
from datetime import UTC, datetime, timedelta

from app.services.market_snapshot_service import latest_snapshot
from tests.test_market_snapshot_latest import _snapshot, db  # noqa: F401


def test_future_snapshot_does_not_displace_observed_snapshot(db):
    db.add(_snapshot(0, 'ok', 'real'))
    future = _snapshot(-1, 'ok', 'future')
    future.metrics = {'fake': {'value': 999}}
    db.add(future)
    db.commit()
    result = latest_snapshot(db)
    assert result['date'] == datetime.now(UTC).date().isoformat()
    assert 'fake' not in result['metrics']


def test_future_generation_is_not_current_evidence(db):
    snapshot = _snapshot(0, 'ok', 'future-generation')
    snapshot.generated_at = datetime.now(UTC) + timedelta(days=1)
    db.add(snapshot)
    db.commit()
    result = latest_snapshot(db)
    assert result['status'] == 'sin datos'
    assert result['metrics'] == {}


def test_future_only_snapshot_returns_unavailable_not_available(db):
    db.add(_snapshot(-1, 'ok', 'future-only'))
    db.commit()
    assert latest_snapshot(db)['coverage'] == 'unavailable'
