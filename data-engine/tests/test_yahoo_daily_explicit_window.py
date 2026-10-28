"""Daily closes use exact dates rather than the provider's broken 7d range."""
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd

from app.services import propicks_price_service as svc


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 28, 9, tzinfo=UTC)


def test_seven_day_window_recovers_dated_close_without_spot_substitution(monkeypatch):
    calls = []
    def history(**kwargs):
        calls.append(kwargs)
        # Same provider: range is null, exact daily date window has the close.
        close = None if 'period' in kwargs else 57.0
        return pd.DataFrame({'Close': [close], 'Adj Close': [close], 'Volume': [100]},
                            index=pd.to_datetime(['2026-10-27']))
    metadata = {'currency': 'EUR', 'exchangeTimezoneName': 'Europe/Madrid'}
    monkeypatch.setattr(svc, 'datetime', FixedDatetime)
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(Ticker=lambda s:
        SimpleNamespace(history=history, get_history_metadata=lambda: metadata)))
    bars = svc.fetch_history_yfinance(['ITX.MC'], period='7d')['ITX.MC']
    assert calls == [{'start': '2026-10-21', 'end': '2026-10-29', 'auto_adjust': False}]
    assert len(bars) == 1
    assert str(bars[0].close) == '57.0'
    assert bars[0].day.isoformat() == '2026-10-27'
    assert bars[0].quote_currency == 'EUR'
    assert bars[0].market_timezone == 'Europe/Madrid'


def test_other_periods_keep_existing_provider_contract(monkeypatch):
    calls = []
    def history(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame()
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(Ticker=lambda s:
        SimpleNamespace(history=history, get_history_metadata=lambda: {})))
    assert svc.fetch_history_yfinance(['AAPL'], period='1y') == {'AAPL': []}
    assert calls == [{'period': '1y', 'auto_adjust': False}]
