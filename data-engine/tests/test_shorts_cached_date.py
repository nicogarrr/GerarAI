"""Persisted FINRA dates must not crash GET or claim future data is current."""
from datetime import UTC, datetime

import pytest

from app.models.entities import ConnectorState
from app.services.short_positions_service import read_shorts
from tests.test_short_positions_service_bordes import _company, db  # noqa: F401

FIXED_NOW = datetime(2026, 11, 14, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_finra_clock(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_NOW.astimezone(tz) if tz else FIXED_NOW.replace(tzinfo=None)

    monkeypatch.setattr("app.services.short_positions_service.datetime", FixedDateTime)


@pytest.mark.parametrize('day', ['not-a-date', '', None, '2026-11-15'])
def test_bad_cached_finra_date_is_degraded_but_preserved(db, day):
    company = _company(db)
    payload = {'source': 'FINRA', 'date': day, 'short_volume': 10, 'total_volume': 100}
    db.add(ConnectorState(tenant_id=1, company_id=company.id, connector='public_shorts',
        feed_url='public-shorts', last_success_at=FIXED_NOW, metadata_=payload))
    db.commit()
    result = read_shorts(db, company)
    assert result['status'] == 'degraded'
    assert result['data'] == payload
    assert 'fecha' in result['reason'].lower()


def test_valid_cached_finra_date_today_is_available(db):
    company = _company(db)
    db.add(ConnectorState(tenant_id=1, company_id=company.id, connector='public_shorts',
        feed_url='public-shorts', last_success_at=FIXED_NOW,
        metadata_={'source': 'FINRA', 'date': FIXED_NOW.date().isoformat()}))
    db.commit()
    assert read_shorts(db, company)['status'] == 'available'
