"""Divisa de cotizacion por listado y subunidades (GBX, ZAc, ILA)."""

from __future__ import annotations

import pytest

from app.valuation.currency import (
    listing_currency,
    listing_quote_unit,
    normalize_currency,
    to_major_units,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GBp", ("GBP", 100)),
        ("GBX", ("GBP", 100)),
        ("GBP", ("GBP", 1)),
        ("ZAc", ("ZAR", 100)),
        ("ZAC", ("ZAR", 100)),
        ("ILA", ("ILS", 100)),
        ("usd", ("USD", 1)),
        ("", (None, 1)),
        (None, (None, 1)),
    ],
)
def test_normalize_currency(raw, expected) -> None:
    assert normalize_currency(raw) == expected


@pytest.mark.parametrize(
    ("ticker", "company_currency", "unit", "major"),
    [
        ("CGEO.L", "USD", "GBX", "GBP"),
        ("CGEO.L", "GBP", "GBX", "GBP"),
        ("NPN.JO", None, "ZAC", "ZAR"),
        ("TEVA.TA", None, "ILA", "ILS"),
        ("SAN.MC", "USD", "EUR", "EUR"),
        ("7203.T", None, "JPY", "JPY"),
        ("BABA", "USD", "USD", "USD"),
        ("XYZ", "GBp", "GBp", "GBP"),
        ("XYZ", None, "USD", "USD"),
    ],
)
def test_listing_quote_unit(ticker, company_currency, unit, major) -> None:
    assert listing_quote_unit(ticker, company_currency) == unit
    assert listing_currency(ticker, company_currency) == major


def test_to_major_units() -> None:
    amount = to_major_units(4255, "GBX")
    assert amount is not None
    assert amount.value == pytest.approx(42.55)
    assert amount.currency == "GBP"
    zar = to_major_units(12345, "ZAc")
    assert zar is not None and zar.value == pytest.approx(123.45) and zar.currency == "ZAR"
    assert to_major_units(10, None) is None


@pytest.mark.parametrize("raw,target,value,expected", [
    ("GBX", "GBP", "4255", "42.55"),
    ("GBP", "GBP", "42.55", "42.55"),
    ("GBP", "GBX", "42.55", "4255"),
    (None, "GBP", "4255", None),
    ("USD", "GBP", "4255", None),
])
def test_price_unit_requires_identity_not_london_suffix(raw, target, value, expected):
    from decimal import Decimal
    from types import SimpleNamespace

    from app.services.price_units import price_in_currency

    company = SimpleNamespace(ticker="CGEO.L", currency="GBP")
    converted = price_in_currency(Decimal(value), quote_currency=raw,
                                  target_currency=target, company=company)
    assert converted == (Decimal(expected) if expected is not None else None)


def test_yahoo_history_preserves_provider_unit(monkeypatch):
    from datetime import date

    import pandas as pd
    import yfinance

    from app.services.propicks_price_service import fetch_history_yfinance

    class Instrument:
        def history(self, **kwargs):
            return pd.DataFrame({"Close": [42.55], "Adj Close": [42.55], "Volume": [10]},
                                index=pd.to_datetime([date(2026, 10, 26)]))
        def get_history_metadata(self):
            return {"currency": "GBP"}

    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: Instrument())
    bars = fetch_history_yfinance(["CGEO.L"])["CGEO.L"]
    assert bars[0].quote_currency == "GBP"  # .L must not force GBX
    assert float(bars[0].close) == 42.55


def test_yahoo_intraday_preserves_explicit_unit_from_fetcher():
    import asyncio
    from datetime import date
    from decimal import Decimal
    from types import SimpleNamespace

    from app.services.market_refresh_service import YahooIntradayPriceProvider

    day = date(2026, 10, 26)
    provider = YahooIntradayPriceProvider(fetcher=lambda symbols: {
        "CGEO.L": (Decimal("42.55"), day, "GBP")
    })
    rows, errors = asyncio.run(provider.fetch([
        SimpleNamespace(ticker="CGEO.L", currency="GBP", exchange="LSE")
    ], as_of=day))
    assert errors == []
    assert rows["CGEO.L"].quote_currency == "GBP"
