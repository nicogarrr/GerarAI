"""Cached payloads need a valid observation time, not just data."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import short_positions_service as service


@pytest.mark.parametrize('stamp', [None, datetime.now(UTC) + timedelta(days=1)])
def test_unverifiable_cache_time_is_degraded_and_keeps_data(monkeypatch, stamp):
    payload = {'source': 'CNMV', 'positions': [], 'public_total_percent': 0}
    state = SimpleNamespace(metadata_=payload, last_success_at=stamp, consecutive_errors=0, last_error=None)
    monkeypatch.setattr(service, '_state', lambda *_: state)
    result = service.read_shorts(None, SimpleNamespace(ticker='GRF'))
    assert result['status'] == 'degraded'
    assert result['data'] == payload
    assert 'fecha de consulta' in result['reason'].lower()


def test_valid_naive_cache_time_remains_available(monkeypatch):
    state = SimpleNamespace(metadata_={'source': 'CNMV'}, last_success_at=datetime.now(UTC).replace(tzinfo=None), consecutive_errors=0, last_error=None)
    monkeypatch.setattr(service, '_state', lambda *_: state)
    result = service.read_shorts(None, SimpleNamespace(ticker='GRF'))
    assert result['status'] == 'available'
    assert result['reason'] is None


@pytest.mark.parametrize('stamp_kind', ['missing', 'future', 'valid'])
@pytest.mark.parametrize('trade_day', [None, 'bad', '2999-01-01', 'today'])
def test_fetch_and_trade_date_validations_coexist(monkeypatch, stamp_kind, trade_day):
    now = datetime.now(UTC)
    stamp = None if stamp_kind == 'missing' else now + timedelta(days=1) if stamp_kind == 'future' else now
    payload = {'source': 'FINRA', 'date': now.date().isoformat() if trade_day == 'today' else trade_day}
    state = SimpleNamespace(metadata_=payload, last_success_at=stamp, consecutive_errors=0, last_error=None)
    monkeypatch.setattr(service, '_state', lambda *_: state)
    result = service.read_shorts(None, SimpleNamespace(ticker='ABC'))
    invalid_stamp = stamp_kind != 'valid'
    invalid_trade = trade_day != 'today'
    assert result['status'] == ('degraded' if invalid_stamp or invalid_trade else 'available')
    if invalid_stamp:
        assert 'fecha de consulta' in result['reason'].lower()
    elif invalid_trade:
        assert 'fecha finra' in result['reason'].lower()
    else:
        assert result['reason'] is None
    assert result['data'] == payload
