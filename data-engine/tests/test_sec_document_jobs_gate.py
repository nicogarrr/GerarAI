"""Behavior tests: SEC document jobs are not emitted from OCI by default.

F359: the SEC blocks datacenter IPs (permanent 403), so process_document
jobs for SEC filings always fail from prod and poisoned the default queue
(5276 messages). The mirror (HF dataset synced by GitHub Actions) keeps
SEC filing metadata flowing; document-download jobs are gated behind
sec_document_jobs_enabled (default False).
"""

from types import SimpleNamespace

import app.services.feed_ingestion_service as feed_module
from app.workers import dramatiq_app


class _FakeFeedService:
    def __init__(self, items):
        self._items = items

    async def poll_sec(self, cik, ticker=None, limit=20):
        return SimpleNamespace(errors=[], status="ok", items=self._items)

    def ingest_news_result(self, db, result, ticker=None):
        return {"created": 1}


class _FakeDB:
    def close(self):
        pass


def _run_actor(monkeypatch, enabled: bool, items):
    sends = []
    monkeypatch.setattr(dramatiq_app, "_session", lambda *a, **k: _FakeDB())
    monkeypatch.setattr(
        dramatiq_app,
        "_companies",
        lambda db, ticker=None: [SimpleNamespace(cik="0000320193", ticker="AAPL")],
    )
    monkeypatch.setattr(
        feed_module, "FeedIngestionService", lambda: _FakeFeedService(items)
    )
    monkeypatch.setattr(
        dramatiq_app.process_document, "send", lambda *a, **k: sends.append((a, k))
    )
    monkeypatch.setattr(
        dramatiq_app.settings, "sec_document_jobs_enabled", enabled
    )
    # Dedup de encolado (5-nov-2026): aqui ninguna URL esta ingerida todavia.
    monkeypatch.setattr(dramatiq_app, "_document_url_ingested", lambda db, url: False)
    # Sin opt-out operativo en estas pruebas.
    monkeypatch.setattr(
        dramatiq_app.settings, "document_ingest_exclusions", "", raising=False
    )
    result = dramatiq_app.refresh_sec_filings.fn()
    return result, sends


def _sec_item():
    return SimpleNamespace(
        url="https://www.sec.gov/Archives/edgar/data/320193/0001.htm",
        title="8-K",
        published_at=None,
    )


def test_sec_document_jobs_not_emitted_by_default(monkeypatch):
    """Default (OCI): no process_document for SEC filings; the skip is
    visible in the payload and filing metadata still flows."""
    result, sends = _run_actor(monkeypatch, enabled=False, items=[_sec_item()])
    assert sends == []
    assert result["documents_queued"] == 0
    assert result["documents_skipped_sec_blocked"] == 1
    assert result["companies_processed"] == 1
    assert result["news_ingested"] == 1


def test_sec_document_jobs_emitted_when_enabled(monkeypatch):
    """Opt-in (e.g. local dev where SEC is reachable): jobs emit as before."""
    result, sends = _run_actor(monkeypatch, enabled=True, items=[_sec_item()])
    assert len(sends) == 1
    assert sends[0][0][3] == "SEC"
    assert result["documents_queued"] == 1
    assert result["documents_skipped_sec_blocked"] == 0


def test_sec_document_jobs_preserve_optional_filing_metadata(monkeypatch):
    item = _sec_item()
    item.metadata = {"form": "8-K", "cik": "0000320193", "report_date": "2026-09-30"}
    result, sends = _run_actor(monkeypatch, enabled=True, items=[item])
    assert len(sends) == 1
    assert result["documents_queued"] == 1
    assert sends[0][1]["filing_metadata"] == item.metadata


def test_sec_document_jobs_without_metadata_keep_legacy_contract(monkeypatch):
    result, sends = _run_actor(monkeypatch, enabled=True, items=[_sec_item()])
    assert result["documents_queued"] == 1
    assert len(sends) == 1
    assert sends[0][1]["filing_metadata"] is None
