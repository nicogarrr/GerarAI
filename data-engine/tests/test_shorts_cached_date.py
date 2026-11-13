"""Persisted FINRA dates must not crash GET or claim future data is current."""
from datetime import UTC, datetime, timedelta

import pytest

from app.models.entities import ConnectorState
from app.services.short_positions_service import read_shorts
from tests.test_short_positions_service_bordes import _company, db  # noqa: F401


@pytest.mark.parametrize('day', ['not-a-date', '', None, (datetime.now(UTC).date() + timedelta(days=1)).isoformat()])
def test_bad_cached_finra_date_is_degraded_but_preserved(db, day):
    company = _company(db)
    payload = {'source': 'FINRA', 'date': day, 'short_volume': 10, 'total_volume': 100}
    db.add(ConnectorState(tenant_id=1, company_id=company.id, connector='public_shorts',
        feed_url='public-shorts', last_success_at=datetime.now(UTC), metadata_=payload))
    db.commit()
    result = read_shorts(db, company)
    assert result['status'] == 'degraded'
    assert result['data'] == payload
    assert 'fecha' in result['reason'].lower()


def test_valid_cached_finra_date_today_is_available(db):
    company = _company(db)
    db.add(ConnectorState(tenant_id=1, company_id=company.id, connector='public_shorts',
        feed_url='public-shorts', last_success_at=datetime.now(UTC),
        metadata_={'source': 'FINRA', 'date': datetime.now(UTC).date().isoformat()}))
    db.commit()
    assert read_shorts(db, company)['status'] == 'available'
