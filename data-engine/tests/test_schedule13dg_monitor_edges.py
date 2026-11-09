"""13D/G scan edges with real SQLite state and isolated connector responses."""

from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, ConnectorState, Schedule13DGFiling
from app.services import schedule13dg_monitor as monitor


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def install(monkeypatch, *, ciks, filings):
    monkeypatch.setattr(monitor, "resolve_ciks", lambda db, symbols, client=None: ciks)
    recent = Mock(side_effect=lambda cik, **kwargs: filings[cik])
    monkeypatch.setattr(monitor.form13dg_connector, "recent_form13dg_filings", recent)
    return recent


def filing(accession="fixture"):
    return {
        "accession_number": accession,
        "document_url": "https://fixture.test/report",
        "form": "SC 13G",
        "filing_date": "2026-11-09",
    }


@pytest.mark.parametrize("value,expected", [(" 000123 ", "123"), (" invalid ", "invalid")])
def test_cik_normalization_preserves_non_numeric_fallback(value, expected):
    assert monitor._normalize_cik(value) == expected


@pytest.mark.parametrize("tickers", [[], ["", " ", None]])
def test_explicit_empty_tickers_skip_watchlist_and_persist_state(db, monkeypatch, tickers):
    watchlist = Mock(side_effect=AssertionError("must not inspect watchlist"))
    monkeypatch.setattr(monitor, "watchlist_tickers", watchlist)
    result = monitor.scan(db, tickers=tickers)
    assert result["status"] == "skipped"
    assert result["reason"] == "watchlist and portfolio are empty"
    watchlist.assert_not_called()
    state = db.scalar(select(ConnectorState).where(ConnectorState.connector == monitor.CONNECTOR_NAME))
    assert state.cursor == "skipped" and state.metadata_["runs"] == 1


def test_unresolved_symbols_are_errors_without_provider_calls(db, monkeypatch):
    recent = install(monkeypatch, ciks={}, filings={})
    result = monitor.scan(db, tickers=[" missing "], delay_seconds=0)
    assert result["status"] == "error"
    assert result["errors"] == ["sin CIK SEC: MISSING"]
    assert result["tickers_scanned"] == 0
    recent.assert_not_called()


def test_list_failure_is_constant_public_error_and_next_issuer_continues(db, monkeypatch):
    install(monkeypatch, ciks={"ONE": "1", "TWO": "2"}, filings={})
    recent = Mock(side_effect=[RuntimeError("private detail"), []])
    monkeypatch.setattr(monitor.form13dg_connector, "recent_form13dg_filings", recent)
    result = monitor.scan(db, tickers=["ONE", "TWO"], delay_seconds=0)
    assert result["status"] == "partial"
    assert result["errors"] == ["ONE: form13dg_list_error"]
    assert result["tickers_scanned"] == 2 and recent.call_count == 2
    assert "private detail" not in str(result)


def test_zero_budget_never_lists_filings(db, monkeypatch):
    recent = install(monkeypatch, ciks={"ONE": "1"}, filings={})
    result = monitor.scan(db, tickers=["ONE"], max_new_fetches=0, delay_seconds=0)
    assert result["errors"] == ["presupuesto de descargas agotado"]
    assert result["status"] == "error" and result["tickers_scanned"] == 0
    recent.assert_not_called()


def test_missing_accession_and_budget_exhaustion_do_not_fetch_more(db, monkeypatch):
    install(
        monkeypatch,
        ciks={"ONE": "1", "TWO": "2"},
        filings={"1": [filing(""), filing("first"), filing("second")]},
    )
    fetch = Mock(return_value="local raw")
    persist = Mock(return_value={"filing_created": True, "status": "unparsed"})
    monkeypatch.setattr(monitor.form13dg_connector, "parse_schedule13dg", lambda _: {})
    monkeypatch.setattr(monitor.schedule13dg_persistence, "persist_filing", persist)
    result = monitor.scan(db, tickers=["ONE", "TWO"], max_new_fetches=1, fetcher=fetch, delay_seconds=0)
    assert result["filings_new"] == 1 and result["filings_unparsed"] == 1
    assert result["tickers_scanned"] == 1 and result["filings_seen"] == 3
    assert result["status"] == "partial"
    assert result["errors"] == ["presupuesto de descargas agotado"]
    fetch.assert_called_once()
    assert fetch.call_args.args[0]["accession_number"] == "first"
    persist.assert_called_once()


def test_default_fetch_failure_is_sanitized_and_delayed(db, monkeypatch):
    install(monkeypatch, ciks={"ONE": "1"}, filings={"1": [filing()]})
    fetch = Mock(side_effect=RuntimeError("private detail"))
    sleep = Mock()
    monkeypatch.setattr(monitor.form13dg_connector, "fetch_filing_document", fetch)
    result = monitor.scan(db, tickers=["ONE"], delay_seconds=0.25, sleeper=sleep, client="local-client")
    assert result["status"] == "partial"
    assert result["errors"] == ["fixture: form13dg_filing_error"]
    fetch.assert_called_once_with("https://fixture.test/report", client="local-client")
    sleep.assert_called_once_with(0.25)
    assert db.scalar(select(Schedule13DGFiling)) is None


def test_rejected_issuer_is_delayed_once_and_never_persisted(db, monkeypatch):
    install(monkeypatch, ciks={"ONE": "0001"}, filings={"0001": [filing()]})
    monkeypatch.setattr(monitor.form13dg_connector, "parse_schedule13dg", lambda _: {"issuer_cik": "2"})
    persist = Mock(side_effect=AssertionError("must not persist mismatched issuer"))
    monkeypatch.setattr(monitor.schedule13dg_persistence, "persist_filing", persist)
    sleep = Mock()
    result = monitor.scan(
        db, tickers=["ONE"], fetcher=lambda _: "local raw", delay_seconds=0.25, sleeper=sleep
    )
    assert result["filings_rejected"] == 1 and result["filings_new"] == 0
    assert result["status"] == "partial"
    persist.assert_not_called()
    sleep.assert_called_once_with(0.25)
