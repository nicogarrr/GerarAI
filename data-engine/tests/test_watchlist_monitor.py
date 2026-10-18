from datetime import date, timedelta

from fastapi.testclient import TestClient

import main
from app.core.database import SessionLocal, init_db
from app.models import Company, MarketPrice, Tenant, ThesisVersion


def _seed_monitor_fixtures() -> int:
    init_db()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).first()
        company = db.query(Company).filter(Company.ticker == "MONTEST").first()
        if company is None:
            company = Company(ticker="MONTEST", name="Monitor Test Co",
                              exchange="NASDAQ", currency="USD",
                              company_type="listed", valuation_model="dcf")
            db.add(company)
            db.flush()
        today = date.today()
        db.query(MarketPrice).filter(MarketPrice.company_id == company.id).delete()
        for i in range(0, 300, 7):
            day = today - timedelta(days=i)
            db.merge(MarketPrice(
                company_id=company.id, date=day,
                open=100, high=105, low=95,
                close=80.0 if i == 210 else 100.0 + i / 10,
                adj_close=None))
        thesis = db.query(ThesisVersion).filter(
            ThesisVersion.company_id == company.id,
            ThesisVersion.version == 3).first()
        if thesis is None:
            db.add(ThesisVersion(
                tenant_id=tenant.id if tenant else 1,
                company_id=company.id, version=3, status="published",
                thesis_markdown="t", executive_summary="s",
                expected_value=150.0))
        db.commit()
        return company.id
    finally:
        db.close()


def test_watchlist_monitor_returns_own_data(monkeypatch):
    _seed_monitor_fixtures()

    async def fake_earnings(desde, hasta, client=None):
        return {"status": "ok", "events": [
            {"symbol": "MONTEST", "date": (date.today() + timedelta(days=9)).isoformat()},
            {"symbol": "OTHER", "date": (date.today() + timedelta(days=3)).isoformat()},
        ], "errors": []}

    monkeypatch.setattr(
        "app.api.routes.watchlist.fetch_earnings_range", fake_earnings)
    client = TestClient(main.app)
    res = client.get("/api/watchlist/monitor", params={"tickers": "montest,NOEXISTE"})
    assert res.status_code == 200
    body = res.json()
    row = body["items"]["MONTEST"]
    assert row["low_52w"] == 80.0
    assert row["low_52w_sessions"] > 30
    assert row["last_close"] is not None
    assert row["fair_value"] == 150.0
    assert row["valuation_side"] == "infravalorada"
    assert row["next_earnings_date"] == (date.today() + timedelta(days=9)).isoformat()
    assert row["next_earnings_source"] == "NASDAQ (api.nasdaq.com)"
    assert "NOEXISTE" not in body["items"]


def test_watchlist_monitor_degrades_without_earnings(monkeypatch):
    _seed_monitor_fixtures()

    async def broken(desde, hasta, client=None):
        raise RuntimeError("nasdaq down")

    monkeypatch.setattr("app.api.routes.watchlist.fetch_earnings_range", broken)
    client = TestClient(main.app)
    res = client.get("/api/watchlist/monitor", params={"tickers": "MONTEST"})
    assert res.status_code == 200
    row = res.json()["items"]["MONTEST"]
    assert row["next_earnings_date"] is None
    assert res.json()["earnings_status"] == "unavailable"
