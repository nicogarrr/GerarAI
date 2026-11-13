"""Bad Yahoo observations cannot leak NaN or desynchronize candle arrays."""
import pytest

from app.api.routes.market import _fetch_yahoo_candles


class Response:
    status_code = 200

    def __init__(self, close, stamp, optional=10):
        self.close, self.stamp, self.optional = close, stamp, optional

    def json(self):
        return {'chart': {'result': [{'timestamp': [self.stamp, 2000],
            'indicators': {'quote': [{'close': [self.close, 20],
                'open': [self.optional, 19], 'high': [self.optional, 21],
                'low': [self.optional, 18], 'volume': [self.optional, 100]}]}}]}}


class Client:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


@pytest.mark.parametrize('close', [float('nan'), float('inf'), True, 'bad', 10**400])
def test_invalid_close_is_skipped_with_its_other_fields(close):
    result = _fetch_yahoo_candles(Client(Response(close, 1000)), 'EXAMPLE', 0, 3000, '1d')
    assert result == {'s': 'ok', 't': [2000], 'c': [20], 'o': [19], 'h': [21], 'l': [18], 'v': [100]}


@pytest.mark.parametrize('stamp', [float('nan'), float('inf'), True, -1, 1000.5, None])
def test_invalid_timestamp_is_skipped_without_dropping_other_candles(stamp):
    result = _fetch_yahoo_candles(Client(Response(10, stamp)), 'EXAMPLE', 0, 3000, '1d')
    assert result['t'] == [2000]
    assert result['c'] == [20]


@pytest.mark.parametrize('optional', [float('nan'), float('inf'), True, 'bad', 10**400])
def test_invalid_optional_fields_are_unknown_without_dropping_close(optional):
    result = _fetch_yahoo_candles(Client(Response(10, 1000, optional)), 'EXAMPLE', 0, 3000, '1d')
    assert result['c'] == [10, 20]
    for key in ('o', 'h', 'l', 'v'):
        assert result[key][0] is None


def test_negative_volume_is_unknown_but_signed_price_is_not_rewritten():
    result = _fetch_yahoo_candles(Client(Response(-10, 1000, -10)), 'EXAMPLE', 0, 3000, '1d')
    assert result['c'][0] == -10
    assert result['o'][0] == -10
    assert result['v'][0] is None
