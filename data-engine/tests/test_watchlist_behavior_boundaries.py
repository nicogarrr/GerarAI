"""Watchlist route failure boundaries: no provider calls for invalid requests,
no stale P/E sold as current, and no fabricated DCA data on provider failure.
All providers are local doubles; no network or model calls.
"""
from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import watchlist as route
from app.models import FinancialFact
from app.models.entities import Base
from app.services import dca_signal_service as svc


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info.update(tenant_id=1, user_id="local-user")
        yield session
    engine.dispose()


@pytest.mark.parametrize("symbol", ["  ", "X" * 25])
def test_invalid_ticker_rejected_before_history_or_quote_fetch(db, monkeypatch, symbol):
    history = Mock(side_effect=AssertionError("must not call provider"))
    monkeypatch.setattr(svc, "fetch_yahoo_history_cached", history)
    for call in [lambda: route.dca_backtest(symbol, start=None, end=None, base=100, db=db),
                 lambda: asyncio.run(route.dca_watch_card(symbol, db=db))]:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 422
    history.assert_not_called()


def test_reversed_backtest_window_does_not_download(db, monkeypatch):
    history = Mock(side_effect=AssertionError("must not call provider"))
    monkeypatch.setattr(svc, "fetch_yahoo_history_cached", history)
    with pytest.raises(HTTPException) as exc:
        route.dca_backtest("AAPL", start="2026-02", end="2026-01", base=100, db=db)
    assert exc.value.status_code == 422
    history.assert_not_called()


@pytest.mark.parametrize("mode", ["backtest", "card"])
def test_history_failure_is_502_not_empty_or_invented_data(db, monkeypatch, mode):
    history = Mock(side_effect=RuntimeError("local provider down"))
    monkeypatch.setattr(svc, "fetch_yahoo_history_cached", history)
    with pytest.raises(HTTPException) as exc:
        if mode == "backtest":
            route.dca_backtest(" aapl ", start=None, end=None, base=100, db=db)
        else:
            asyncio.run(route.dca_watch_card(" aapl ", db=db))
    assert exc.value.status_code == 502
    history.assert_called_once_with("AAPL")


@pytest.mark.parametrize("mode", ["backtest", "card"])
def test_empty_history_declares_unavailable_without_quote(db, monkeypatch, mode):
    from app.services.extended_quote_service import extended_quote_service
    history = Mock(return_value=SimpleNamespace(rows=[], currency=None))
    quote = Mock(side_effect=AssertionError("no quote needed without bars"))
    monkeypatch.setattr(svc, "fetch_yahoo_history_cached", history)
    monkeypatch.setattr(extended_quote_service, "get", quote)
    out = (route.dca_backtest(" NEW ", start=None, end=None, base=100, db=db)
           if mode == "backtest" else asyncio.run(route.dca_watch_card(" NEW ", db=db)))
    assert out["symbol"] == "NEW"
    assert out["available"] is False
    assert "Sin histórico" in out["reason"]
    assert "currency" not in out
    if mode == "card":
        assert out["timeframes"] == []
    quote.assert_not_called()


def test_annual_eps_age_boundary_is_calendar_months_not_day_estimate():
    def fact(period):
        return FinancialFact(period=period, fiscal_year=2024, fiscal_quarter="FY", metric="eps_diluted")
    row = fact("2024-12-31")
    assert route._stale_annual_reason(row, date(2026, 6, 30)) is None
    one = route._stale_annual_reason(row, date(2026, 7, 1))
    two = route._stale_annual_reason(row, date(2026, 7, 2))
    assert one is not None and "18 meses y 1 día" in one
    assert two is not None and "18 meses y 2 días" in two
    assert route._stale_annual_reason(fact("not-a-date"), date(2026, 7, 1)) is None
    assert route._stale_annual_reason(row, date(2024, 12, 30)) is None


def test_staleness_missing_future_and_exact_max_age(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(dca_max_data_age_days=3))
    today = date(2026, 1, 10)
    assert route._dca_staleness(None, today) == (None, False)
    assert route._dca_staleness(date(2026, 1, 11), today) == (0, False)
    assert route._dca_staleness(date(2026, 1, 7), today) == (3, False)
    assert route._dca_staleness(date(2026, 1, 6), today) == (4, True)
