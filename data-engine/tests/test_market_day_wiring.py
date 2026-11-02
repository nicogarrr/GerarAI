"""Días sin sesión en la bolsa del ticker: la pasada diaria de DCA y la de
alertas de precio no evalúan ese ticker (festivos de Madrid, Londres, NYSE)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import AlertRule, Base, Company, MarketPrice, Tenant, WatchItem
from app.services.alert_rule_service import AlertRuleService
from app.services.dca_signal_service import FetchedHistory, evaluate_watchlist
from app.services.market_calendar import exchange_for_ticker, ticker_market_closed

EASTER_MONDAY = date(2026, 4, 6)  # Madrid y Londres cerrados, NYSE abierta
US_HOLIDAY = date(2026, 7, 3)  # 4 de julio (observado): NYSE cerrada, Madrid abierta
NORMAL_DAY = date(2026, 10, 27)


@pytest.mark.parametrize(
    ("ticker", "exchange"),
    [("SAN.MC", "XMAD"), ("tsco.l", "XLON"), ("AAPL", "XNYS"), ("BRK-B", "XNYS"),
     ("SAP.DE", None), ("^GSPC", None), ("BTC-USD", None), ("EURUSD=X", None), ("", None)],
)
def test_exchange_for_ticker(ticker, exchange):
    assert exchange_for_ticker(ticker) == exchange


def test_ticker_market_closed_by_exchange_calendar():
    assert ticker_market_closed("SAN.MC", EASTER_MONDAY) is True
    assert ticker_market_closed("TSCO.L", EASTER_MONDAY) is True
    assert ticker_market_closed("AAPL", EASTER_MONDAY) is False
    assert ticker_market_closed("AAPL", US_HOLIDAY) is True
    assert ticker_market_closed("SAN.MC", US_HOLIDAY) is False
    for ticker in ("SAN.MC", "TSCO.L", "AAPL"):
        assert ticker_market_closed(ticker, NORMAL_DAY) is False
    # Bolsa desconocida o fecha fuera del calendario: como siempre (no se salta).
    assert ticker_market_closed("SAP.DE", EASTER_MONDAY) is False
    assert ticker_market_closed("AAPL", date(1990, 1, 1)) is False


class _Fetcher:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, symbol: str) -> FetchedHistory:
        self.calls.append(symbol)
        return FetchedHistory(rows=[])


@pytest.fixture
def dca_db(monkeypatch):
    monkeypatch.setenv("DCA_ALERTS_ENABLED", "false")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t-mkt", name="t"))
        session.commit()
        session.info["tenant_id"] = 1
        session.info["user_id"] = "u-1"
        for symbol in ("SAN.MC", "AAPL", "SAP.DE"):
            session.add(WatchItem(tenant_id=1, symbol=symbol))
        session.commit()
        yield session
    get_settings.cache_clear()


def _dca(db, day: date, *, skip: bool = True):
    fetcher = _Fetcher()
    now = datetime(day.year, day.month, day.day, 23, 15, tzinfo=UTC)
    summary = evaluate_watchlist(
        db, fetcher=fetcher, now=now, today=day, use_db_fallback=False, skip_closed_markets=skip
    )
    closed = {s["symbol"] for s in summary["skipped"] if s["reason"] == "mercado_cerrado"}
    return set(fetcher.calls), closed


def test_dca_sweep_skips_ticker_on_its_exchange_holiday(dca_db):
    fetched, closed = _dca(dca_db, EASTER_MONDAY)
    assert closed == {"SAN.MC"}
    assert "AAPL" in fetched and "SAN.MC" not in fetched
    # Sufijo desconocido: se evalúa como siempre.
    assert "SAP.DE" not in closed


def test_dca_sweep_skips_us_ticker_on_nyse_holiday(dca_db):
    fetched, closed = _dca(dca_db, US_HOLIDAY)
    assert closed == {"AAPL"}
    assert "AAPL" not in fetched


def test_dca_sweep_normal_day_unchanged(dca_db):
    assert _dca(dca_db, NORMAL_DAY) == _dca(dca_db, NORMAL_DAY, skip=False)
    _fetched, closed = _dca(dca_db, NORMAL_DAY)
    assert closed == set()


def test_dca_manual_evaluation_does_not_skip(dca_db):
    _fetched, closed = _dca(dca_db, EASTER_MONDAY, skip=False)
    assert closed == set()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _rule(db: Session, ticker: str, exchange: str, currency: str) -> AlertRule:
    company = Company(
        ticker=ticker, name=ticker, exchange=exchange, currency=currency,
        sector="x", industry="x", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    db.add(MarketPrice(
        company_id=company.id, date=date.today(), open=Decimal("210"), high=Decimal("210"),
        low=Decimal("210"), close=Decimal("210"), adj_close=Decimal("210"), source="Finnhub",
    ))
    db.commit()
    return AlertRuleService().create(db, company, rule_type="price_above", operator=">", value=200)


def _statuses(db, rules, **kwargs):
    by_id = {r["rule_id"]: r["status"] for r in AlertRuleService().evaluate_all(db, **kwargs)}
    return {name: by_id[rule.id] for name, rule in rules.items()}


def test_price_rules_skip_closed_exchange_only(db):
    rules = {
        "SAN.MC": _rule(db, "SAN.MC", "MCE", "EUR"),
        "AAPL": _rule(db, "AAPL", "NASDAQ", "USD"),
        "SAP.DE": _rule(db, "SAP.DE", "GER", "EUR"),
    }
    out = _statuses(db, rules, skip_closed_markets=True, market_day=EASTER_MONDAY)
    assert out["SAN.MC"] == "skipped_market_closed"
    assert out["AAPL"] != "skipped_market_closed"
    assert out["SAP.DE"] != "skipped_market_closed"
    san = rules["SAN.MC"]
    db.refresh(san)
    assert san.last_evaluated_at is None and san.trigger_count == 0


def test_price_rules_normal_day_and_manual_unchanged(db):
    rules = {"SAN.MC": _rule(db, "SAN.MC", "MCE", "EUR"), "AAPL": _rule(db, "AAPL", "NASDAQ", "USD")}
    out = _statuses(db, rules, skip_closed_markets=True, market_day=NORMAL_DAY)
    assert "skipped_market_closed" not in out.values()


def test_price_rules_without_flag_are_evaluated_on_holiday(db):
    rules = {"SAN.MC": _rule(db, "SAN.MC", "MCE", "EUR")}
    out = _statuses(db, rules, market_day=EASTER_MONDAY)
    assert out["SAN.MC"] != "skipped_market_closed"
