"""Una fila sin volumen no debe abortar el lote de precios Yahoo."""
import sys
from datetime import date
from types import SimpleNamespace

from app.services.propicks_price_service import fetch_history_yfinance


class _History:
    def iterrows(self):
        yield SimpleNamespace(date=lambda: date(2026, 10, 22)), {"Close": 100.0, "Adj Close": 98.0, "Volume": float("nan")}
        yield SimpleNamespace(date=lambda: date(2026, 10, 23)), {"Close": 101.0, "Adj Close": 99.0, "Volume": 270}


class _Ticker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, **kwargs):
        return _History()

    def get_history_metadata(self):
        return {"currency": "USD", "exchangeTimezoneName": "America/New_York"}


def test_volumen_nan_no_aborta_lote(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=_Ticker))
    bars = fetch_history_yfinance(["AAPL", "MSFT"])
    # NaN de la fuente = volumen ausente (None), no 0: un 0 explicito es dato
    # y un re-sync sin volumen no debe pisar el guardado (479abb3be).
    assert [bar.volume for bar in bars["AAPL"]] == [None, 270]
    assert len(bars["MSFT"]) == 2
