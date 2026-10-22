from datetime import UTC, date, datetime

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


def test_merge_disagreement_with_yahoo_non_estimate_is_not_confirmed():
    """NVDA 19-oct-2026: Yahoo 17-nov (estimate=False) vs NASDAQ 18-nov: al
    menos una fuente proyecta, luego la fecha no puede exhibirse confirmada."""
    row = merge_candidate(
        {"date": date(2026, 11, 17), "estimate": False},
        {"date": date(2026, 11, 18), "session": None, "fiscal": None},
    )
    assert row["source"] == "yahoo" and row["confirmed"] is False
    assert "NASDAQ publica otra fecha" in row["label"]


def test_merge_nasdaq_only_has_unknown_confirmation_and_none_when_empty():
    row = merge_candidate(None, {"date": date(2026, 10, 20), "session": None, "fiscal": None})
    assert row["confirmed"] is None and row["source"] == "nasdaq"
    assert merge_candidate(None, None) is None


def _tenant_with_watch(db, tickers):
    from uuid import uuid4

    from app.models import Tenant

    uid = uuid4().hex[:6].upper()
    tenant = Tenant(external_id=f"ed-{uid}", name=uid)
    db.add(tenant)
    db.flush()
    names = {}
    for base in tickers:
        ticker = f"{base}{uid}" if not base.endswith(".L") else f"{base[:-2]}{uid}.L"
        names[base] = ticker
        db.add(Company(ticker=ticker, name=f"{ticker} Inc", exchange="LSE" if ticker.endswith(".L") else "NYSE",
                       currency="GBX" if ticker.endswith(".L") else "USD",
                       company_type="research_candidate", valuation_model="unassigned"))
        db.add(WatchItem(symbol=ticker, company=ticker, tenant_id=tenant.id))
    db.commit()
    db.info["tenant_id"] = tenant.id
    return names


def test_refresh_writes_rows_keeps_manual_and_reports_missing():
    init_db()
    db = SessionLocal()
    try:
        n = _tenant_with_watch(db, ["ZQA", "ZQB", "ZQC.L"])
        db.add(EarningsDate(ticker=n["ZQC.L"], event_date=date(2026, 10, 28), source="manual",
                            source_label="Comunicado", source_url="https://example.test/rns"))
        db.commit()
        result = refresh_earnings_dates(
            db, today=TODAY,
            yahoo_fetcher=lambda syms: {n["ZQA"]: {"date": date(2026, 10, 20), "estimate": False}},
            nasdaq_fetcher=lambda tickers, today: {},
        )
        assert result["followed"] == 3 and result["written"] == 1
        assert result["without_date"] == [n["ZQB"]]
        cal = followed_calendar(
            db, TODAY, date(2026, 12, 31), now=datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        )
        by = {e["ticker"]: e for d in cal["days"] for e in d["events"]}
        assert by[n["ZQA"]]["confirmed"] is True and by[n["ZQA"]]["session"] is None
        assert by[n["ZQC.L"]]["source_url"] == "https://example.test/rns"
        assert cal["without_date_in_range"] == [n["ZQB"]]
        assert cal["stale_date_in_range"] == []
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
        n = _tenant_with_watch(db, ["ZSA", "ZSB"])
        old = datetime.now(UTC) - timedelta(days=5)
        db.add(EarningsDate(ticker=n["ZSA"], event_date=date(2026, 11, 2), source="yahoo",
                            source_label="Yahoo", fetched_at=old))
        db.add(EarningsDate(ticker=n["ZSB"], event_date=date(2026, 11, 3), source="manual",
                            source_label="Comunicado", fetched_at=old))
        db.commit()
        cal = followed_calendar(db, date(2026, 11, 1), date(2026, 11, 30))
        tickers = {e["ticker"] for d in cal["days"] for e in d["events"]}
        assert n["ZSA"] not in tickers and n["ZSA"] in cal["without_date_in_range"]
        assert n["ZSB"] in tickers
        # Caducada no es lo mismo que sin fecha: se marca aparte para no decir "sin publicar".
        assert cal["stale_date_in_range"] == [n["ZSA"]]
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


def test_fetch_yahoo_dates_uses_a_real_client_without_reopening_it(monkeypatch):
    """Regresion: `with client:` tras haber usado el cliente lanzaba RuntimeError."""
    from datetime import UTC, datetime

    import httpx

    from app.services import earnings_dates_service as svc

    raw = int(datetime(2026, 10, 20, 20, 0, tzinfo=UTC).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"quoteSummary": {"result": [{"calendarEvents": {"earnings": {
            "earningsDate": [{"raw": raw}], "isEarningsDateEstimate": False}}}]}}
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.get("https://fc.yahoo.com")  # el cliente ya se ha usado, como en produccion
    monkeypatch.setattr(svc, "_yahoo_session", lambda: (client, "crumb"))
    monkeypatch.setattr(svc, "YAHOO_PAUSE_S", 0)
    out = svc.fetch_yahoo_dates({"CB": "CB"})
    assert out == {"CB": {"date": date(2026, 10, 20), "estimate": False}}
    assert client.is_closed


def test_is_fresh_expires_automatic_rows_only():
    from datetime import UTC, datetime, timedelta

    from app.services.earnings_dates_service import is_fresh

    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    old = now - timedelta(days=4)
    assert not is_fresh(EarningsDate(ticker="X", event_date=date(2026, 11, 1), source="yahoo", fetched_at=old), now)
    assert is_fresh(EarningsDate(ticker="X", event_date=date(2026, 11, 1), source="yahoo", fetched_at=now), now)
    assert is_fresh(EarningsDate(ticker="X", event_date=date(2026, 11, 1), source="manual", fetched_at=old), now)


def test_followed_calendar_keeps_history_without_hiding_next_date_or_ghosts():
    from datetime import UTC, datetime, timedelta

    init_db()
    db = SessionLocal()
    try:
        n = _tenant_with_watch(db, ["ZHA", "ZHB", "ZHC", "ZHD"])
        now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
        old = now - timedelta(days=9)
        fresh = now - timedelta(hours=1)
        # ZHA: ultimo resultado confirmado (pasado, sin renovar) + proxima fecha vigente.
        db.add(EarningsDate(ticker=n["ZHA"], event_date=date(2026, 10, 15), source="yahoo",
                            source_label="Yahoo", confirmed=True, fetched_at=old))
        db.add(EarningsDate(ticker=n["ZHA"], event_date=date(2027, 1, 20), source="yahoo",
                            source_label="Yahoo", confirmed=False, fetched_at=fresh))
        # ZHB: solo historia confirmada -> aparece, pero sigue "sin fecha" (no hay proxima).
        db.add(EarningsDate(ticker=n["ZHB"], event_date=date(2026, 10, 19), source="nasdaq+yahoo",
                            source_label="N+Y", confirmed=True, fetched_at=old))
        # ZHC: pasada estimada/desconocida = fantasma, no se muestra como publicada.
        db.add(EarningsDate(ticker=n["ZHC"], event_date=date(2026, 10, 16), source="yahoo",
                            source_label="Yahoo", confirmed=False, fetched_at=old))
        db.add(EarningsDate(ticker=n["ZHD"], event_date=date(2026, 10, 17), source="nasdaq",
                            source_label="N", confirmed=None, fetched_at=old))
        db.commit()
        cal = followed_calendar(db, date(2026, 10, 14), date(2027, 1, 31), now=now)
        events = [e for d in cal["days"] for e in d["events"]]
        by = {}
        for e in events:
            by.setdefault(e["ticker"], []).append(e["date"])
        assert by[n["ZHA"]] == ["2026-10-15", "2027-01-20"]
        assert by[n["ZHB"]] == ["2026-10-19"]
        assert n["ZHC"] not in by and n["ZHD"] not in by
        assert cal["without_date_in_range"] == sorted([n["ZHB"], n["ZHC"], n["ZHD"]])
    finally:
        db.rollback()
        db.close()


def test_followed_calendar_manual_wins_per_side_and_default_horizon_unchanged():
    from datetime import UTC, datetime, timedelta

    init_db()
    db = SessionLocal()
    try:
        n = _tenant_with_watch(db, ["ZMA"])
        now = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
        fresh = now - timedelta(hours=1)
        db.add(EarningsDate(ticker=n["ZMA"], event_date=date(2026, 10, 25), source="yahoo",
                            source_label="Yahoo", confirmed=False, fetched_at=fresh))
        db.add(EarningsDate(ticker=n["ZMA"], event_date=date(2026, 10, 28), source="manual",
                            source_label="Comunicado", fetched_at=now - timedelta(days=30)))
        db.commit()
        cal = followed_calendar(db, date(2026, 10, 21), date(2026, 12, 20), now=now)
        dates = [e["date"] for d in cal["days"] for e in d["events"] if e["ticker"] == n["ZMA"]]
        assert dates == ["2026-10-28"]
        assert cal["without_date_in_range"] == []
    finally:
        db.rollback()
        db.close()
