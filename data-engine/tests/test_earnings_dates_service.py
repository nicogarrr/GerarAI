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


def test_market_timezone_and_yahoo_day_in_market_zone():
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from app.services.earnings_dates_service import market_timezone

    assert market_timezone("CB") == "America/New_York"
    assert market_timezone("7203.T") == "Asia/Tokyo"
    assert market_timezone("CGEO.L") == "Europe/London"
    assert market_timezone("BRK.B") == "America/New_York"
    assert market_timezone("XYZ.QQ") is None
    # 5-nov 00:00 JST es 4-nov 15:00 UTC: el dia correcto es el 5.
    raw = int(datetime(2026, 11, 4, 15, 0, tzinfo=UTC).timestamp())
    assert datetime.fromtimestamp(raw, ZoneInfo("Asia/Tokyo")).date() == date(2026, 11, 5)
    assert datetime.fromtimestamp(raw, UTC).date() == date(2026, 11, 4)


def test_stale_automatic_dates_are_omitted_but_manual_stays():
    from datetime import UTC, datetime, timedelta

    init_db()
    db = SessionLocal()
    try:
        for t in ("ZSA", "ZSB"):
            if db.scalar(select(Company).where(Company.ticker == t)) is None:
                db.add(Company(ticker=t, name=t, exchange="NYSE", currency="USD",
                               company_type="research_candidate", valuation_model="unassigned"))
            if db.scalar(select(WatchItem).where(WatchItem.symbol == t)) is None:
                db.add(WatchItem(symbol=t, company=t))
        old = datetime.now(UTC) - timedelta(days=5)
        db.add(EarningsDate(ticker="ZSA", event_date=date(2026, 11, 2), source="yahoo",
                            source_label="Yahoo", fetched_at=old))
        db.add(EarningsDate(ticker="ZSB", event_date=date(2026, 11, 3), source="manual",
                            source_label="Comunicado", fetched_at=old))
        db.commit()
        cal = followed_calendar(db, date(2026, 11, 1), date(2026, 11, 30))
        tickers = {e["ticker"] for d in cal["days"] for e in d["events"]}
        assert "ZSA" not in tickers and "ZSA" in cal["without_date_in_range"]
        assert "ZSB" in tickers
    finally:
        db.rollback()
        db.close()


def test_followed_companies_are_scoped_to_the_tenant():
    from app.models import Tenant
    from app.services.earnings_dates_service import followed_companies

    init_db()
    db = SessionLocal()
    try:
        ta, tb = Tenant(external_id="ed-ta", name="A"), Tenant(external_id="ed-tb", name="B")
        db.add_all([ta, tb])
        db.flush()
        for t in ("ZTA", "ZTB"):
            if db.scalar(select(Company).where(Company.ticker == t)) is None:
                db.add(Company(ticker=t, name=t, exchange="NYSE", currency="USD",
                               company_type="research_candidate", valuation_model="unassigned"))
        db.add_all([
            WatchItem(symbol="ZTA", company="A", tenant_id=ta.id),
            WatchItem(symbol="ZTB", company="B", tenant_id=tb.id),
        ])
        db.commit()
        db.info["tenant_id"] = ta.id
        assert "ZTA" in followed_companies(db) and "ZTB" not in followed_companies(db)
        db.info["tenant_id"] = tb.id
        assert "ZTB" in followed_companies(db) and "ZTA" not in followed_companies(db)
    finally:
        db.rollback()
        db.close()
