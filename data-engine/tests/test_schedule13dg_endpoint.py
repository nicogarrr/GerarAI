"""Endpoint POST /api/ownership/schedule-13dg/sync: solo tickers SEGUIDOS
(watchlist o cartera del tenant); cualquier otro se rechaza."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.ownership import schedule_13dg_sync
from app.core.database import SessionLocal, init_db
from app.models.entities import Company, Position, Schedule13DGFiling, WatchItem
from app.services import schedule13dg_monitor


def _db():
    init_db()
    db = SessionLocal()
    db.query(WatchItem).delete()
    db.query(Position).delete()
    # Other suites persist ZZT filings: an empty-read test must own its fixture.
    db.query(Schedule13DGFiling).filter(
        Schedule13DGFiling.issuer_ticker.in_(["ZZT", "PFT"])
    ).delete()
    db.query(Company).filter(Company.ticker.in_(["ZZT", "PFT"])).delete()
    db.commit()
    return db


def test_sync_rejects_unfollowed_ticker():
    db = _db()
    with pytest.raises(HTTPException) as excinfo:
        schedule_13dg_sync(ticker="ZZT", db=db)
    assert excinfo.value.status_code == 404
    db.close()


def test_sync_allows_watchlist_ticker(monkeypatch):
    db = _db()
    db.add(WatchItem(symbol="ZZT", company="ZZ Test Corp"))
    db.commit()
    captured: dict = {}

    def fake_scan(db_arg, **kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(schedule13dg_monitor, "scan", fake_scan)
    result = schedule_13dg_sync(ticker=" zzt ", db=db)
    assert result == {"status": "ok"}
    assert captured["tickers"] == ["ZZT"]
    db.close()


def test_sync_allows_portfolio_ticker(monkeypatch):
    db = _db()
    company = Company(
        ticker="PFT", name="Portfolio Corp", exchange="NASDAQ",
        company_type="compounders", valuation_model="dcf", cik="0001780312",
    )
    db.add(company)
    db.flush()
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    captured: dict = {}

    def fake_scan(db_arg, **kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(schedule13dg_monitor, "scan", fake_scan)
    result = schedule_13dg_sync(ticker="PFT", db=db)
    assert result == {"status": "ok"}
    assert captured["tickers"] == ["PFT"]
    db.close()


def test_get_filings_still_open_for_any_ticker():
    """La lectura no cambia: cualquier ticker devuelve lo persistido (o vacio)."""
    from app.api.routes.ownership import schedule_13dg

    db = _db()
    result = schedule_13dg(ticker="ZZT", db=db)
    assert result["ticker"] == "ZZT"
    assert result["count"] == 0
    assert result["filings"] == []
    db.close()
