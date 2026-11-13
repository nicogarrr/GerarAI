"""La fecha diaria válida no valida la liquidación de la posición quincenal."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import short_positions_service as service


@pytest.mark.parametrize('settlement', [None, '', 'bad', '2026-02-30', 123, '2999-01-01', 'missing'])
def test_invalid_settlement_is_degraded_without_hiding_payload(monkeypatch, settlement):
    now = datetime.now(UTC)
    payload = {'source': 'FINRA', 'date': now.date().isoformat(),
               'short_interest': {'settlement_date': settlement, 'short_interest': 20}}
    if settlement == 'missing':
        payload['short_interest'].pop('settlement_date')
    state = SimpleNamespace(metadata_=payload, last_success_at=now,
                            consecutive_errors=0, last_error=None)
    monkeypatch.setattr(service, '_state', lambda *_: state)
    result = service.read_shorts(None, SimpleNamespace(ticker='ABC'))
    assert result['status'] == 'degraded'
    assert result['data'] == payload
    assert 'Fecha FINRA' in result['reason']


@pytest.mark.parametrize('interest', [None, {'settlement_date': datetime.now(UTC).date().isoformat()},
    {'settlement_date': (datetime.now(UTC).date() - timedelta(days=15)).isoformat()}])
def test_absent_interest_or_valid_settlement_keeps_daily_available(monkeypatch, interest):
    now = datetime.now(UTC)
    payload = {'source': 'FINRA', 'date': now.date().isoformat(), 'short_interest': interest}
    state = SimpleNamespace(metadata_=payload, last_success_at=now,
                            consecutive_errors=0, last_error=None)
    monkeypatch.setattr(service, '_state', lambda *_: state)
    result = service.read_shorts(None, SimpleNamespace(ticker='ABC'))
    assert result['status'] == 'available'
    assert result['reason'] is None
