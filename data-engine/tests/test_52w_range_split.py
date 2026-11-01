"""Rango de 52 semanas con un split dentro del año (cierres brutos).

``market_prices.close`` guarda el cierre cotizado: antes de un split ese cierre
está en la base vieja. Un contrasplit 1:10 dentro del año dejaba el mínimo de
52 semanas en un cierre pre-split diez veces menor (y un split 10:1, el máximo
diez veces mayor), en la ficha y en el monitor de la watchlist. Con un split
efectivo dentro de la ventana solo cuentan los cierres desde el split; con
menos de las sesiones mínimas la ficha cae al rango de Yahoo como ya hacía.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, CorporateAction, MarketPrice, Tenant
from app.services import key_stats_service as ks
from tests.auth_helpers import auth_settings, signed_request

TODAY = date(2026, 6, 30)
SECRET = "watchlist-split-range-secret-"


def test_range_from_closes_ignores_closes_before_a_split_in_the_window():
    split_day = TODAY - timedelta(days=100)
    rows = [
        (TODAY - timedelta(days=300), 2.0),  # pre-contrasplit 1:10 (base vieja)
        (TODAY - timedelta(days=101), 2.5),
        (split_day, 25.0),
        (TODAY - timedelta(days=50), 22.0),
        (TODAY, 30.0),
    ]
    rng = ks.range_from_closes(rows, TODAY, split_dates=[split_day])
    assert rng is not None
    assert (rng.low, rng.high) == (22.0, 30.0)
    assert rng.sessions == 3


def test_range_from_closes_split_outside_window_changes_nothing():
    rows = [(TODAY - timedelta(days=300), 80.0), (TODAY, 100.0)]
    rng = ks.range_from_closes(rows, TODAY, split_dates=[TODAY - timedelta(days=500), TODAY + timedelta(days=5)])
    assert rng is not None
    assert (rng.low, rng.high, rng.sessions) == (80.0, 100.0, 2)


def test_monitor_low_52w_skips_closes_before_reverse_split(monkeypatch) -> None:
    monkeypatch.setattr(auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET))
    init_db()
    tenant = f"wm-split-{uuid4().hex[:8]}"
    ticker = f"WS{uuid4().hex[:6].upper()}"
    today = date.today()
    split_day = today - timedelta(days=60)
    db = SessionLocal()
    tenant_row = Tenant(external_id=tenant, name="Watchlist split test")
    db.add(tenant_row)
    company = Company(ticker=ticker, name="Split Co", exchange="NYSE", currency="USD",
                      company_type="operating", valuation_model="unassigned")
    db.add(company)
    db.flush()
    db.add(CorporateAction(tenant_id=tenant_row.id, company_id=company.id, action_type="reverse_split",
                           effective_date=split_day, ratio=Decimal("0.1")))
    for days_ago, close in [(200, 1.5), (61, 2.0), (60, 20.0), (30, 18.0), (1, 21.0)]:
        db.add(MarketPrice(company_id=company.id, date=today - timedelta(days=days_ago),
                           close=Decimal(str(close)), source="test"))
    db.commit()
    db.close()

    res = signed_request(TestClient(main.app), SECRET, tenant, "wm-split-user", "GET",
                         "/api/watchlist/monitor", params={"tickers": ticker})

    assert res.status_code == 200, res.text
    item = res.json()["items"][ticker]
    assert item["low_52w"] == 18.0
    assert item["low_52w_date"] == (today - timedelta(days=30)).isoformat()
    assert item["low_52w_sessions"] == 3
    assert item["last_close"] == 21.0
