"""``fetch_yahoo_history`` sin red: yfinance sustituido por un doble (ronda 2 de mutacion).

77 mutantes de ``dca_signal_service`` vivian en esta funcion porque ningun test
la ejecutaba (``no tests``). Se fija el filtrado de cierres, el ``Adj Close``
opcional, la fecha del indice y la divisa de ``history_metadata``.
"""

from __future__ import annotations

import sys
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.dca_signal_service import fetch_yahoo_history


class _FakeTicker:
    calls: list = []

    def __init__(self, symbol, frame, metadata):
        self.symbol = symbol
        self._frame = frame
        if metadata is not _NO_METADATA:
            self.history_metadata = metadata

    def history(self, **kwargs):
        _FakeTicker.calls.append((self.symbol, kwargs))
        return self._frame


_NO_METADATA = object()


class _BrokenMetadata:
    def get(self, key):
        raise RuntimeError("metadata rota")


def _install(monkeypatch, frame, metadata=_NO_METADATA):
    _FakeTicker.calls = []
    fake = SimpleNamespace(Ticker=lambda symbol: _FakeTicker(symbol, frame, metadata))
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def _frame(rows, *, index=None):
    index = index or pd.to_datetime([f"2025-01-0{i + 1}" for i in range(len(rows))])
    return pd.DataFrame(rows, index=index)


def test_filtra_cierres_invalidos_y_normaliza_adj_close(monkeypatch):
    frame = _frame([
        {"Close": 10.5, "Adj Close": 10.0},           # valido
        {"Close": 0.0, "Adj Close": 1.0},             # cierre 0: fuera
        {"Close": -3.0, "Adj Close": 1.0},            # cierre negativo: fuera
        {"Close": float("nan"), "Adj Close": 1.0},    # NaN: fuera
        {"Close": float("inf"), "Adj Close": 1.0},    # infinito: fuera
        {"Close": "n/a", "Adj Close": 1.0},           # no numerico: fuera
        {"Close": 11.0, "Adj Close": float("nan")},   # adj NaN -> None
        {"Close": 12.0, "Adj Close": 0.0},            # adj 0 -> None
        {"Close": 13.0, "Adj Close": "x"},            # adj no numerico -> None
    ])
    _install(monkeypatch, frame, {"currency": "GBp"})
    result = fetch_yahoo_history("TSCO.L", period="5y")
    assert _FakeTicker.calls == [("TSCO.L", {"period": "5y", "auto_adjust": False})]
    assert [(r.day, r.close, r.adj_close) for r in result.rows] == [
        (date(2025, 1, 1), 10.5, 10.0),
        (date(2025, 1, 7), 11.0, None),
        (date(2025, 1, 8), 12.0, None),
        (date(2025, 1, 9), 13.0, None),
    ]
    assert result.currency == "GBp"


def test_sin_columna_adj_close_y_periodo_por_defecto(monkeypatch):
    _install(monkeypatch, _frame([{"Close": 5.0}, {"Close": None}]), {"currency": "USD"})
    result = fetch_yahoo_history("AAPL")
    assert _FakeTicker.calls == [("AAPL", {"period": "max", "auto_adjust": False})]
    assert [(r.day, r.close, r.adj_close) for r in result.rows] == [(date(2025, 1, 1), 5.0, None)]
    assert result.currency == "USD"


def test_adj_close_negativo_o_infinito_es_none(monkeypatch):
    _install(monkeypatch, _frame([
        {"Close": 5.0, "Adj Close": -1.0},
        {"Close": 6.0, "Adj Close": float("inf")},
        {"Close": 7.0, "Adj Close": 6.5},
    ]), {"currency": "EUR"})
    rows = fetch_yahoo_history("SAN.MC").rows
    assert [r.adj_close for r in rows] == [None, None, 6.5]


def test_indice_sin_date_se_usa_tal_cual(monkeypatch):
    frame = pd.DataFrame([{"Close": 5.0}], index=[date(2024, 6, 3)])
    _install(monkeypatch, frame, {"currency": "EUR"})
    assert fetch_yahoo_history("X").rows[0].day == date(2024, 6, 3)


@pytest.mark.parametrize("metadata", [_NO_METADATA, None, {}, _BrokenMetadata()])
def test_divisa_ausente_o_rota_es_none(monkeypatch, metadata):
    _install(monkeypatch, _frame([{"Close": 5.0}]), metadata)
    result = fetch_yahoo_history("X")
    assert result.currency is None
    assert len(result.rows) == 1
