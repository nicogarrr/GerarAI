from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import Company, EarningsDate, WatchItem
from app.services.earnings_dates_service import (
    followed_calendar,
    merge_candidate,
    refresh_earnings_dates,
)

TODAY = date(2026, 10, 19)


def test_merge_same_date_keeps_nasdaq_session_and_yahoo_confirmation():
    row = merge_candidate(
        {"date": date(2026, 10, 20), "estimate": False},
        {"date": date(2026, 10, 20), "session": "after_market", "fiscal": "Sep/2026"},
    )
    assert row["source"] == "nasdaq+yahoo" and row["confirmed"] is True
    assert row["session"] == "after_market" and row["fiscal"] == "Sep/2026"


def test_merge_disagreement_prefers_yahoo_and_drops_session():
    row = merge_candidate(
        {"date": date(2026, 10, 21), "estimate": True},
        {"date": date(2026, 10, 20), "session": "after_market", "fiscal": "Sep/2026"},
    )
    assert row["source"] == "yahoo" and row["confirmed"] is False and row["session"] is None


def test_merge_nasdaq_only_has_unknown_confirmation_and_none_when_empty():
    row = merge_candidate(None, {"date": date(2026, 10, 20), "session": None, "fiscal": None})
    assert row["confirmed"] is None and row["source"] == "nasdaq"
    assert merge_candidate(None, None) is None


def test_refresh_writes_rows_keeps_manual_and_reports_missing():
    init_db()
    db = SessionLocal()
    try:
        for t in ("ZQA", "ZQB", "ZQC.L"):
            if db.scalar(select(Company).where(Company.ticker == t)) is None:
                db.add(Company(ticker=t, name=f"{t} Inc", exchange="LSE" if t.endswith(".L") else "NYSE",
                               currency="GBX" if t.endswith(".L") else "USD",
                               company_type="research_candidate", valuation_model="unassigned"))
            if db.scalar(select(WatchItem).where(WatchItem.symbol == t)) is None:
                db.add(WatchItem(symbol=t, company=t))
        db.add(EarningsDate(ticker="ZQC.L", event_date=date(2026, 10, 28), source="manual",
                            source_label="Comunicado", source_url="https://example.test/rns"))
        db.commit()
        result = refresh_earnings_dates(
            db, today=TODAY,
            yahoo_fetcher=lambda syms: {"ZQA": {"date": date(2026, 10, 20), "estimate": False}},
            nasdaq_fetcher=lambda tickers, today: {},
        )
        assert result["written"] == 1
        assert result["without_date"] == ["ZQB"]
        cal = followed_calendar(db, TODAY, date(2026, 12, 31))
        by = {e["ticker"]: e for d in cal["days"] for e in d["events"]}
        assert by["ZQA"]["confirmed"] is True and by["ZQA"]["session"] is None
        assert by["ZQC.L"]["source_url"] == "https://example.test/rns"
        assert "ZQB" in cal["without_date_in_range"]
    finally:
        db.rollback()
        db.close()
