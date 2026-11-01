"""Fechas en el borde del calendario (0001-01-01, 9999-12-31): 400, nunca 500.

`hasta=0001-01-01` restaba 183 días y `desde=9999-12-31` sumaba 60: Python
lanza OverflowError y la API respondía 500 «Internal server error». Una fecha
fuera de rango es un error del cliente.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from app.core.database import SessionLocal, init_db
from app.models import Company


@pytest.fixture()
def client_and_ticker():
    init_db()
    ticker = f"OVF{uuid4().hex[:4].upper()}"
    db = SessionLocal()
    db.add(Company(ticker=ticker, name="Overflow test", exchange="TEST", currency="EUR",
                   company_type="stock", valuation_model="dcf"))
    db.commit()
    db.close()
    return TestClient(main.app, raise_server_exceptions=False), ticker


@pytest.mark.parametrize("query", ["hasta=0001-01-01", "desde=0001-01-01&hasta=9999-12-31", "hasta=9999-12-31"])
def test_timeline_out_of_range_dates_are_400(client_and_ticker, query) -> None:
    client, ticker = client_and_ticker
    res = client.get(f"/api/companies/{ticker}/events/timeline?{query}")
    assert res.status_code in (200, 400), res.text
    assert res.status_code != 500


def test_timeline_min_date_is_400(client_and_ticker) -> None:
    client, ticker = client_and_ticker
    res = client.get(f"/api/companies/{ticker}/events/timeline?hasta=0001-01-01")
    assert res.status_code == 400, res.text


def test_macro_calendar_max_date_is_400(client_and_ticker) -> None:
    client, _ = client_and_ticker
    res = client.get("/api/macro-calendar/events?desde=9999-12-31")
    assert res.status_code == 400, res.text
