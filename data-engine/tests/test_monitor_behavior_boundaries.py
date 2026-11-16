"""Monitoring boundaries: source failures are explicit, quotas do not enqueue,
and identity-less runs never borrow another tenant's state. No network calls.
"""
import asyncio
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Document, WatchItem
from app.models.entities import Base
from app.services import tracked_analysis as tracked
from app.services import tracked_financial_refresh as refresh


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info.update(tenant_id=1, user_id="u1")
        yield session
    engine.dispose()


def test_refresh_without_stored_facts_is_not_success(db, monkeypatch):
    c = Company(ticker="LOCAL", name="Local", exchange="NYSE", currency="USD",
                company_type="operating", valuation_model="dcf")
    db.add(c)
    db.commit()
    calls = []
    async def empty(self, **kwargs):
        calls.append(kwargs["company"].ticker)
        return {"facts_imported": 0}
    monkeypatch.setattr(refresh.FinancialIngestionService, "refresh_from_sec", empty)
    result = asyncio.run(refresh.refresh_free_financials(db, c, now=datetime(2026, 11, 1, tzinfo=UTC)))
    assert calls == ["LOCAL"]
    assert result == {"provider": "SEC", "last_refreshed_at": None,
                      "facts_imported": 0, "status": "error", "reason": "sin_hechos_financieros"}


@pytest.mark.parametrize("raw", ["broken-date", "2026-11-01T12:00:00"])
def test_refresh_timestamp_is_parsed_or_absent_not_fabricated(db, raw):
    c = Company(ticker="LOCAL", name="Local", exchange="NYSE", currency="USD",
                company_type="operating", valuation_model="dcf")
    db.add(c)
    db.flush()
    db.add(Document(tenant_id=1, company_id=c.id, title="SEC XBRL facts - LOCAL", source_type="SEC",
                    metadata_={"last_refreshed_at": raw}))
    db.commit()
    actual = refresh.last_sec_refresh(db, c)
    assert actual == (None if raw == "broken-date" else datetime(2026, 11, 1, 12, tzinfo=UTC))


def test_backfill_without_tenant_skips_before_any_read_or_enqueue(monkeypatch):
    db = Mock(spec=Session)
    db.info = {}
    enqueue = Mock(side_effect=AssertionError("no identity must not enqueue"))
    monkeypatch.setattr(tracked, "enqueue_tracked_analysis", enqueue)
    assert tracked.backfill_watchlist_theses(db) == {"status": "skipped", "reason": "sin tenant"}
    db.scalars.assert_not_called()
    enqueue.assert_not_called()


def test_empty_watchlist_finishes_without_generation(db, monkeypatch):
    enqueue = Mock(side_effect=AssertionError("empty watchlist must not enqueue"))
    monkeypatch.setattr(tracked, "enqueue_tracked_analysis", enqueue)
    assert tracked.backfill_watchlist_theses(db) == {"status": "ok", "enqueued": [], "skipped": {}}
    enqueue.assert_not_called()


def test_zero_backfill_budget_names_skipped_tickers_without_enqueuing(db, monkeypatch):
    db.add(WatchItem(tenant_id=1, symbol="LOCAL", auto_analysis_enabled=True))
    db.commit()
    enqueue = Mock(side_effect=AssertionError("quota must not enqueue"))
    monkeypatch.setattr(tracked, "enqueue_tracked_analysis", enqueue)
    assert tracked.backfill_watchlist_theses(db, limit=0) == {
        "status": "ok", "enqueued": [], "skipped": {"LOCAL": "tope_diario"}}
    enqueue.assert_not_called()


def test_resolve_empty_ciks_does_not_scan_company_table_or_sec(monkeypatch):
    from app.services import insider_monitor as monitor
    db = Mock(spec=Session)
    lookup = Mock(side_effect=AssertionError("empty request cannot use SEC"))
    monkeypatch.setattr(monitor, "_cik_for_ticker", lookup)
    assert monitor.resolve_ciks(db, []) == {}
    db.scalars.assert_not_called()
    lookup.assert_not_called()


def test_unresolved_cik_remains_absent_and_is_not_written(db, monkeypatch):
    from app.services import insider_monitor as monitor
    lookup = Mock(return_value=None)
    monkeypatch.setattr(monitor, "_cik_for_ticker", lookup)
    assert monitor.resolve_ciks(db, ["UNKNOWN"]) == {}
    lookup.assert_called_once_with("UNKNOWN", None)


def test_zero_download_budget_never_requests_form4(db, monkeypatch):
    from app.services import insider_monitor as monitor
    monkeypatch.setattr(monitor, "watchlist_tickers", lambda *_: ["LOCAL"])
    monkeypatch.setattr(monitor, "resolve_ciks", lambda *_, **__: {"LOCAL": "0000000001"})
    fetch = Mock(side_effect=AssertionError("zero budget cannot call SEC"))
    monkeypatch.setattr(monitor.form4_connector, "recent_form4_filings", fetch)
    result = monitor.scan(db, tenant_id=1, max_new_fetches=0, delay_seconds=0)
    assert result["tickers_scanned"] == result["filings_seen"] == result["filings_new"] == 0
    assert result["errors"] == ["presupuesto de descargas agotado"]
    fetch.assert_not_called()
