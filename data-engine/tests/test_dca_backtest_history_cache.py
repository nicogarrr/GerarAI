"""Backtest DCA: el historico de Yahoo no se descarga entero en cada vista.

Antes cada apertura del backtest bajaba el historico "max" (~11.000 dias) y lo
recorria con ``iterrows``: ~0,5 s de CPU por vista mas la descarga. Ahora la
vista usa una cache de 10 min por simbolo (datos publicos); un fallo no se
cachea y el job diario de senales sigue leyendo siempre fresco.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from app.services import dca_signal_service as svc
from app.services.dca_signal_service import FetchedHistory, PriceRow


@pytest.fixture(autouse=True)
def _clean_cache():
    cache = getattr(svc, "_history_cache", None)
    if cache is not None:
        cache.clear()
    yield
    if cache is not None:
        cache.clear()


def _rows():
    start = date(2015, 1, 2)
    return [PriceRow(day=start + timedelta(days=i), close=100.0 + i % 30) for i in range(0, 3000, 1)]


def test_backtest_view_downloads_history_once(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from app.core.database import init_db

    init_db()
    calls: list[str] = []

    def fake_fetch(symbol):
        calls.append(symbol)
        return FetchedHistory(rows=_rows(), currency="USD")

    monkeypatch.setattr(svc, "fetch_yahoo_history", fake_fetch)
    client = TestClient(main.app)
    first = client.get("/api/watchlist/dca-signals/ZZCACHE/backtest")
    second = client.get("/api/watchlist/dca-signals/zzcache/backtest?base=200")
    assert first.status_code == 200 and second.status_code == 200
    assert calls == ["ZZCACHE"]


def test_failure_is_not_cached(monkeypatch):
    attempts = {"n": 0}

    def flaky(symbol):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("yahoo caido")
        return FetchedHistory(rows=_rows(), currency="USD")

    monkeypatch.setattr(svc, "fetch_yahoo_history", flaky)
    with pytest.raises(RuntimeError):
        svc.fetch_yahoo_history_cached("AAPL")
    assert svc.fetch_yahoo_history_cached("AAPL").currency == "USD"
    assert svc.fetch_yahoo_history_cached("aapl").currency == "USD"
    assert attempts["n"] == 2


def test_column_parse_keeps_row_filters(monkeypatch):
    idx = pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06"])
    hist = pd.DataFrame(
        {"Close": [10.0, float("nan"), 0.0, 12.0], "Adj Close": [9.5, 1.0, 1.0, float("nan")]},
        index=idx,
    )

    class FakeTicker:
        history_metadata = {"currency": "EUR"}

        def __init__(self, symbol):
            pass

        def history(self, period, auto_adjust):
            return hist

    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    got = svc.fetch_yahoo_history("X")
    assert [(r.day, r.close, r.adj_close) for r in got.rows] == [
        (date(2024, 6, 3), 10.0, 9.5),
        (date(2024, 6, 6), 12.0, None),
    ]
    assert got.currency == "EUR"
