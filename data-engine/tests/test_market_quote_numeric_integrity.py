"""Yahoo quotes cannot serialize nonfinite numbers as observed prices."""
import json

import httpx
import pytest

from app.api.routes.market import _fetch_yahoo_quote


def fetch(closes=(10, 20), meta=None, optional=20, stamps=None):
    payload = {'chart': {'result': [{'meta': meta or {},
        'timestamp': stamps or [], 'indicators': {'quote': [{
        'close': list(closes), 'open': [optional] * len(closes),
        'high': [optional] * len(closes), 'low': [optional] * len(closes)}]}}]}}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        # json= normally rejects NaN; external JSON decoders may return it.
        client.get = lambda *args, **kwargs: type('Response', (), {'status_code': 200, 'json': lambda self: payload})()
        return _fetch_yahoo_quote(client, 'EXAMPLE')


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, 'bad', 10**400])
def test_invalid_current_close_is_not_a_quote(value):
    assert fetch(closes=(10, value)) is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, 'bad', 10**400])
def test_invalid_previous_close_does_not_invent_change(value):
    result = fetch(closes=(value, 20))
    assert result is not None and result['c'] == 20
    assert result['pc'] is None and result['d'] is None and result['dp'] is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, 'bad', 10**400])
def test_invalid_optional_price_and_live_fields_are_unknown(value):
    result = fetch(meta={'regularMarketPrice': value, 'regularMarketTime': value}, optional=value)
    for key in ('o', 'h', 'l', 'live_c', 'live_t'):
        assert result[key] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('stamp', [float('nan'), float('inf'), True, -1, 1000.5, 10**400])
def test_invalid_candle_timestamp_is_unknown(stamp):
    result = fetch(stamps=[1000, stamp], meta={'exchangeTimezoneName': 'Europe/Madrid'})
    assert result['c'] == 20
    assert result['ct'] is None and result['cd'] is None


def test_overflowing_percentage_is_unknown_without_discarding_prices():
    result = fetch(closes=(1e-308, 1e308))
    assert result['c'] == 1e308 and result['pc'] == 1e-308
    assert result['dp'] is None
