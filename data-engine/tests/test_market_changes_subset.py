"""compute_session_changes(tickers=...) debe dar las MISMAS filas que el cálculo completo."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.models.entities import Company, MarketPrice
from app.services import market_change


@pytest.fixture()
def seeded():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    tag = uuid4().hex[:6].upper()
    tickers = [f"R{tag}{i}" for i in range(6)]
    companies = [
        Company(
            ticker=t,
            name=f"Rend {t}",
            exchange="NASDAQ",
            currency="USD",
            company_type="operating",
            valuation_model="dcf",
        )
        for t in tickers
    ]
    db.add_all(companies)
    db.commit()
    base = date(2026, 10, 20)  # martes
    days = [base - timedelta(days=k) for k in (0, 1, 4, 5, 6)]  # laborables
    for idx, company in enumerate(companies):
        for k, day in enumerate(days):
            if idx == 5 and k == 0:
                continue  # sin cierre de la última sesión: fuera de la comparación
            db.add(
                MarketPrice(
                    company_id=company.id,
                    date=day,
                    open=Decimal("1"),
                    high=Decimal("1"),
                    low=Decimal("1"),
                    close=Decimal(str(10 + idx + k)),
                    volume=1000 * (idx + 1),
                    source="yfinance",
                    quote_currency="USD",
                )
            )
    db.commit()
    try:
        yield db, tickers
    finally:
        ids = [c.id for c in companies]
        db.query(MarketPrice).filter(MarketPrice.company_id.in_(ids)).delete(synchronize_session=False)
        db.query(Company).filter(Company.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_subset_rows_identical_to_full_universe(seeded):
    db, tickers = seeded
    full, _, full_session = market_change.compute_session_changes(db)
    wanted = {tickers[0], tickers[3].lower(), tickers[5]}
    subset, _, session = market_change.compute_session_changes(db, tickers=wanted)
    assert session == full_session
    by_ticker = {row["ticker"]: row for row in full}
    assert sorted(row["ticker"] for row in subset) == sorted([tickers[0], tickers[3], tickers[5]])
    for row in subset:
        assert row == by_ticker[row["ticker"]]


def test_empty_or_unknown_tickers_return_nothing(seeded):
    db, _ = seeded
    assert market_change.compute_session_changes(db, tickers=[]) == ([], 0, None)
    assert market_change.compute_session_changes(db, tickers=[" "]) == ([], 0, None)
    rows, _, _ = market_change.compute_session_changes(db, tickers=["NOEXISTE_XYZ"])
    assert rows == []


def test_changes_endpoint_matches_full_computation(seeded):
    db, tickers = seeded
    from main import app

    full, _, _ = market_change.compute_session_changes(db)
    expected = {row["ticker"]: row for row in full if row["ticker"] in tickers[:2]}
    response = TestClient(app).get("/api/market/changes", params={"tickers": ",".join(tickers[:2])})
    assert response.status_code == 200
    items = response.json()["items"]
    assert set(items) == set(expected)
    for ticker, row in expected.items():
        assert items[ticker]["change_pct"] == row["change_pct"]
        assert items[ticker]["price"] == row["price"]
        assert items[ticker]["previous_close"] == row["previous_close"]
