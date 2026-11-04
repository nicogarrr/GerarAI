"""Filas de analistas anteriores al listado actual: fuera para todos los tickers.

Antes había una fecha escrita a mano solo para SPCX (el ETF que usaba ese
símbolo hasta que SpaceX empezó a cotizar el 2026-06-12). Cualquier otro
ticker reutilizado, o cualquier salida a bolsa, seguía mezclando objetivos de
otro instrumento. Ahora la fecha sale de Yahoo (``firstTradeDate`` del chart)
para cualquier ticker, y SPCX deja de ser un caso especial.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.services import analyst_targets_service as svc

TODAY = datetime.now(UTC).date()


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(svc, "CACHE_TTL_SECONDS", 0)


def _records(listed: date) -> list[dict]:
    before = listed - timedelta(days=30)
    after = listed + timedelta(days=3)
    return [
        {"date": before.isoformat(), "firm": "Old ETF Desk", "price_target": 25.0},
        {"date": after.isoformat(), "firm": "New Coverage", "price_target": 210.0},
    ]


def _service_with(monkeypatch, *, first_trade: date | None, listed: date) -> list[str]:
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {
            "records": _records(listed),
            "consensus": {"current": 180.0},
            "currency": "USD",
            "quote_type": "EQUITY",
            "first_trade_date": first_trade,
        },
    )
    return [row.firm for row in asyncio.run(svc.AnalystTargetsService().get("NEWCO")).rows]


def test_rows_before_the_listing_first_trade_are_dropped_for_any_ticker(monkeypatch):
    listed = TODAY - timedelta(days=60)
    assert _service_with(monkeypatch, first_trade=listed, listed=listed) == ["New Coverage"]


def test_without_first_trade_date_nothing_is_filtered(monkeypatch):
    listed = TODAY - timedelta(days=60)
    assert _service_with(monkeypatch, first_trade=None, listed=listed) == ["New Coverage", "Old ETF Desk"]


def test_spcx_keeps_its_cut_through_the_general_rule(monkeypatch):
    # El mismo corte que antes estaba escrito a mano, ahora con la fecha de Yahoo.
    monkeypatch.setattr(
        svc,
        "_fetch_sync",
        lambda symbol: {
            "records": [
                {"date": "2026-05-01", "firm": "Old ETF Desk", "price_target": 25.0},
                {"date": "2026-07-01", "firm": "New Coverage", "price_target": 210.0},
            ],
            "consensus": {},
            "currency": "USD",
            "quote_type": "EQUITY",
            "first_trade_date": date(2026, 6, 12),
        },
    )
    rows = asyncio.run(svc.AnalystTargetsService().get("SPCX")).rows
    assert [row.firm for row in rows] == ["New Coverage"]


@pytest.mark.parametrize(
    "raw",
    [
        datetime(2026, 6, 12, 9, 30, tzinfo=timezone(timedelta(hours=-4))),
        date(2026, 6, 12),
        int(datetime(2026, 6, 12, 13, 30, tzinfo=UTC).timestamp()),
        "2026-06-12 09:30:00-04:00",
    ],
)
def test_first_trade_date_parses_every_shape_yahoo_returns(raw):
    assert svc._first_trade_date(raw) == date(2026, 6, 12)


@pytest.mark.parametrize("raw", [None, True, 0, -5, float("nan"), "n/d", object()])
def test_first_trade_date_rejects_garbage(raw):
    assert svc._first_trade_date(raw) is None


def test_fetch_sync_reads_first_trade_date_from_yahoo_chart_metadata(monkeypatch):
    class _Ticker:
        upgrades_downgrades = None
        analyst_price_targets: dict = {}
        fast_info = {"currency": "USD", "quoteType": "EQUITY"}

        def __init__(self, symbol):
            self.symbol = symbol

        def get_history_metadata(self):
            return {"firstTradeDate": datetime(2026, 6, 12, 9, 30, tzinfo=timezone(timedelta(hours=-4)))}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))
    assert svc._fetch_sync("SPCX")["first_trade_date"] == date(2026, 6, 12)


def test_fetch_sync_survives_metadata_failure(monkeypatch):
    class _Ticker:
        upgrades_downgrades = None
        analyst_price_targets: dict = {}
        fast_info = {"currency": "USD", "quoteType": "EQUITY"}

        def __init__(self, symbol):
            self.symbol = symbol

        def get_history_metadata(self):
            raise RuntimeError("chart caído")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_Ticker))
    data = svc._fetch_sync("AAPL")
    assert data["first_trade_date"] is None
    assert data["currency"] == "USD"
