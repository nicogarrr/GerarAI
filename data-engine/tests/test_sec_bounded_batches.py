from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.feed_ingestion_service as feed
from app.workers import dramatiq_app as actors
from app.workers import sec_batch


@pytest.fixture
def harness(monkeypatch):
    calls, sends, documents = [], [], []
    db = SimpleNamespace(close=lambda: calls.append("close"), rollback=lambda: calls.append("rollback"))
    companies = [SimpleNamespace(ticker=x, cik="123") for x in ("A", "B", "C", "D", "E", "F", "G")]
    monkeypatch.setattr(actors, "_session", lambda *a: db)
    monkeypatch.setattr(actors, "_companies", lambda *a: companies)
    monkeypatch.setattr(actors, "_redis_client", lambda: None)
    monkeypatch.setattr(actors.settings, "sec_document_jobs_enabled", False)
    monkeypatch.setattr(actors.refresh_sec_filings, "send", lambda **k: sends.append(k))
    monkeypatch.setattr(actors.process_document, "send", lambda *a, **k: documents.append((a, k)))
    monkeypatch.setattr(actors, "_document_url_ingested", lambda *a: False)
    monkeypatch.setattr(actors, "_document_ingest_excluded", lambda *a: False)
    errors = {}
    items = []

    class Service:
        async def poll_sec(self, cik, *, ticker, limit):
            calls.append((ticker, limit))
            if ticker in errors:
                raise errors[ticker]
            return SimpleNamespace(items=items, errors=[], status="ok")

        def ingest_news_result(self, *a, **k):
            return {"created": 1}

    monkeypatch.setattr(feed, "FeedIngestionService", Service)
    return SimpleNamespace(calls=calls, sends=sends, documents=documents,
                           companies=companies, items=items, errors=errors)


def test_batch_continuations_cover_all_companies_once_and_preserve_context(harness):
    args = dict(tenant_id=7, user_id="owner", ticker=None, limit=20)
    results = []
    while True:
        results.append(actors.refresh_sec_filings.fn(**args))
        if not results[-1]["truncated"]:
            break
        args = harness.sends[-1]
        assert args["tenant_id"] == 7 and args["user_id"] == "owner"
    assert [x[0] for x in harness.calls if isinstance(x, tuple)] == list("ABCDEFG")
    assert [r["companies_attempted"] for r in results] == [3, 3, 1]
    assert [r["next_cursor"] for r in results] == ["C", "F", None]
    assert results[-1]["status"] == "ok"


def test_time_budget_checkpoints_after_one_company(harness, monkeypatch):
    ticks = iter([0, 61])
    monkeypatch.setattr(sec_batch, "monotonic", lambda: next(ticks))
    result = actors.refresh_sec_filings.fn()
    assert result["companies_attempted"] == 1
    assert harness.sends[0]["start_after"] == "A"


def test_errors_are_visible_and_cursor_progresses(harness):
    harness.errors["A"] = TimeoutError("source budget")
    result = actors.refresh_sec_filings.fn()
    assert result["errors"][0]["ticker"] == "A"
    assert result["companies_processed"] == 2
    assert result["next_cursor"] == "C"
    assert "rollback" in harness.calls


def test_no_cik_empty_or_finished_batches_do_not_requeue(harness):
    harness.companies[:] = [SimpleNamespace(ticker="A", cik=None)]
    result = actors.refresh_sec_filings.fn()
    assert result["companies_attempted"] == 0
    assert not result["truncated"]
    assert harness.sends == []


def test_document_budget_does_not_reset_between_chunks(harness, monkeypatch):
    monkeypatch.setattr(actors.settings, "sec_document_jobs_enabled", True)
    monkeypatch.setattr(actors.settings, "document_enqueue_max_per_poll", 2)
    harness.items.append(SimpleNamespace(url="https://www.sec.gov/a", title="8-K", published_at=None))
    first = actors.refresh_sec_filings.fn(limit=500)
    assert first["documents_queued"] == 2
    assert harness.sends[-1]["document_budget"] == 0
    second = actors.refresh_sec_filings.fn(**harness.sends[-1])
    assert second["documents_queued"] == 0
    assert all(x[1] == 20 for x in harness.calls if isinstance(x, tuple))


def test_continuation_enqueue_failure_is_not_reported_as_success(harness, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("broker unavailable")
    monkeypatch.setattr(actors.refresh_sec_filings, "send", fail)
    result = actors.refresh_sec_filings.fn()
    assert result["status"] == "error"
    assert harness.calls[-1] == "close"


def test_sec_actor_routing_and_coalescence_cursor():
    assert actors.refresh_sec_filings.queue_name == "sec"
    assert actors.refresh_sec_filings.options["time_limit"] == 180_000
    assert "start_after" in actors._COALESCE_POLICIES["refresh_sec_filings"]["key_parts"]


def test_poll_has_timeout_and_cancels_without_extra_request(monkeypatch):
    import asyncio
    monkeypatch.setattr(sec_batch, "POLL_TIMEOUT_SECONDS", 0.001)
    cancelled = []
    async def wait():
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    with pytest.raises(TimeoutError):
        asyncio.run(sec_batch.bounded_poll(wait()))
    assert cancelled == [True]


def test_sec_queue_is_consumed_only_outside_default():
    import yaml
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_sequence(node))
    compose = yaml.load((Path(__file__).resolve().parents[2] / "docker-compose.prod.yml").read_text(), Loader=Loader)
    external = compose["services"]["worker-externa"]
    command = external["command"]
    assert command[command.index("-Q") + 1:] == ["externa", "sec"]
    assert "sec" not in compose["services"]["worker"]["command"]
    assert external["deploy"]["resources"]["limits"]["memory"] == "1G"
    assert command[command.index("--threads") + 1] == "${EXTERNA_THREADS:-2}"


def test_document_dedup_opt_out_and_missing_url(harness, monkeypatch):
    monkeypatch.setattr(actors.settings, "sec_document_jobs_enabled", True)
    item = SimpleNamespace(url="https://www.sec.gov/same", title="8-K", published_at=None)
    harness.companies[:] = harness.companies[:1]
    harness.items[:] = [SimpleNamespace(url=None), item, item]
    result = actors.refresh_sec_filings.fn()
    assert result["documents_queued"] == 1
    monkeypatch.setattr(actors, "_document_url_ingested", lambda *a: True)
    result = actors.refresh_sec_filings.fn()
    assert result["documents_skipped_known"] == 2
    monkeypatch.setattr(actors, "_document_ingest_excluded", lambda *a: True)
    result = actors.refresh_sec_filings.fn()
    assert result["documents_skipped_excluded"] == 1


def test_connector_errors_do_not_disappear(harness, monkeypatch):
    class Service:
        async def poll_sec(self, *a, **k):
            return SimpleNamespace(errors=["SEC 429"], items=[], status="error")
        def ingest_news_result(self, *a, **k):
            return {"created": 0}
    monkeypatch.setattr(feed, "FeedIngestionService", Service)
    result = actors.refresh_sec_filings.fn()
    assert result["companies_processed"] == 0
    assert result["errors"][0] == {"ticker": "A", "source": "sec", "message": "SEC 429"}


def test_single_ticker_and_finished_cursor_do_not_continue(harness):
    harness.companies[:] = harness.companies[:1]
    result = actors.refresh_sec_filings.fn(ticker="A", limit=0)
    assert result["status"] == "ok"
    assert harness.calls[0] == ("A", 1)
    result = actors.refresh_sec_filings.fn(ticker="A", start_after="A")
    assert result["companies_attempted"] == 0
    assert harness.sends == []


def test_coalescence_does_not_drop_continuation_but_suppresses_completed_duplicate(harness, monkeypatch):
    class Redis:
        def __init__(self):
            self.store = {}
        def delete(self, key):
            self.store.pop(key, None)
        def set(self, key, value, nx=False, ex=None):
            if key in self.store:
                return False
            self.store[key] = value
            return True
        def eval(self, script, nkeys, key, token):
            if self.store.get(key) == token:
                self.delete(key)
    # Use one persistent client so coalescence is real across messages.
    redis = Redis()
    monkeypatch.setattr(actors, "_redis_client", lambda: redis)
    args = {}
    for _ in range(3):
        result = actors.refresh_sec_filings.fn(**args)
        if result["truncated"]:
            args = harness.sends[-1]
    assert result["status"] == "ok"
    duplicate = actors.refresh_sec_filings.fn(**args)
    assert duplicate["reason"] == "fresh_or_running"
    assert len([x for x in harness.calls if isinstance(x, tuple)]) == 7
