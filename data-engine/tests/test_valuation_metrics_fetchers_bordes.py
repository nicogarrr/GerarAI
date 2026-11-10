"""Fetchers con clientes locales: ninguna llamada de red pese a ejercitar adaptadores."""

import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import yfinance

from app.core.config import get_settings
from app.services import thesis_evidence_service
from app.services import valuation_metrics_service as svc
from app.services.connectors.finnhub import FinnhubClient


class _Series:
    def items(self):
        return [(datetime(2026, 1, 1), v) for v in [2.123456789, -1, float("nan"), float("inf"), "bad"]]


@pytest.mark.parametrize("currency", ["GBp", None])
def test_yahoo_redondea_y_descarta_invalidos(monkeypatch, currency):
    # Guard intacto en producción; aquí cliente y su propiedad se sustituyen por objetos locales.
    monkeypatch.setattr(svc, "_network_forbidden_in_tests", lambda: None)
    monkeypatch.setattr(
        yfinance,
        "Ticker",
        lambda symbol: SimpleNamespace(dividends=_Series(), history_metadata={"currency": currency}),
    )
    event = {"date": "2026-01-01", "amount": "2.123457"}
    if currency:
        event["currency"] = currency
    assert svc.default_dividend_fetcher("TEST") == [event]


def test_yahoo_fallos_y_metadata_rota(monkeypatch):
    monkeypatch.setattr(svc, "_network_forbidden_in_tests", lambda: None)

    def broken(symbol):
        raise ValueError("offline")

    monkeypatch.setattr(yfinance, "Ticker", broken)
    assert svc.default_dividend_fetcher("TEST") is None
    monkeypatch.setattr(
        yfinance, "Ticker", lambda symbol: SimpleNamespace(dividends=None, history_metadata={})
    )
    assert svc.default_dividend_fetcher("TEST") is None

    class MetadataBroken:
        dividends = _Series()

        @property
        def history_metadata(self):
            raise RuntimeError("no metadata")

    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: MetadataBroken())
    assert svc.default_dividend_fetcher("TEST") == [{"date": "2026-01-01", "amount": "2.123457"}]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2.5", Decimal("0.025")),
        (0, Decimal(0)),
        (-1, None),
        ("bad", None),
        ("NaN", None),
        ("Infinity", None),
        (None, None),
    ],
)
def test_finnhub_fraccion_y_no_inventa_yield(monkeypatch, raw, expected):
    monkeypatch.setattr(svc, "_network_forbidden_in_tests", lambda: None)
    monkeypatch.setattr(get_settings(), "finnhub_api_key", "unit-test-placeholder")
    calls = []

    async def metric(self, ticker, *, max_retries):
        calls.append((ticker, max_retries))
        return {"dividendYieldIndicatedAnnual": raw}

    monkeypatch.setattr(FinnhubClient, "metric", metric)
    monkeypatch.setattr(thesis_evidence_service, "_await_sync", lambda factory: asyncio.run(factory()))
    assert svc.default_finnhub_yield_fetcher("TEST") == expected
    assert calls == [("TEST", 0)]


def test_finnhub_error_y_sin_clave(monkeypatch):
    monkeypatch.setattr(svc, "_network_forbidden_in_tests", lambda: None)
    monkeypatch.setattr(get_settings(), "finnhub_api_key", None)
    assert svc.default_finnhub_yield_fetcher("TEST") is None
    monkeypatch.setattr(get_settings(), "finnhub_api_key", "unit-test-placeholder")

    def fail(fn):
        raise ValueError("offline")

    monkeypatch.setattr(thesis_evidence_service, "_await_sync", fail)
    assert svc.default_finnhub_yield_fetcher("TEST") is None
