"""Presupuesto de tiempo de refresh_rss_feeds.

Hallazgo de prod (22:07 UTC): la corrida del tenant 10 murio con
TimeLimitExceeded a los 601 s. Los feeds se sondean en serie (hasta 20 s de
timeout por feed) y la ingesta de cada lote suma: sin presupuesto propio, una
corrida lenta choca con el time_limit de dramatiq (600 s) y el siguiente tick
repite el barrido entero. Con el presupuesto, la corrida para a tiempo, declara
los feeds diferidos en el resultado y deja el trabajo restante al proximo tick.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.workers import dramatiq_app


class _FakeDB:
    """Sesion minima: guarda los ConnectorState en memoria (entre ticks)."""

    def __init__(self, states=None):
        self.states = states if states is not None else []

    def scalars(self, _query):
        return SimpleNamespace(all=lambda: list(self.states))

    def add(self, obj):
        if obj not in self.states:
            self.states.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass

    def close(self):
        pass


class _FakeService:
    def __init__(self, results):
        self._results = results
        self.polls = 0
        self.polled_urls = []

    async def poll_rss(self, url, *, ticker=None, source_label=None):
        self.polls += 1
        self.polled_urls.append(url)
        return self._results[url]

    def ingest_news_result(self, db, result, **kwargs):
        return {"created": 0}


class _Clock:
    """Reloj falso: cada llamada devuelve el siguiente valor."""

    def __init__(self, values):
        self._values = iter(values)

    def monotonic(self):
        return next(self._values)


@pytest.fixture
def rss_env(monkeypatch):
    feeds = [
        SimpleNamespace(url=f"https://feed{i}.example/rss", ticker=None, label=None, lane=None)
        for i in range(4)
    ]
    results = {
        feed.url: SimpleNamespace(errors=[], status="ok", items=[])
        for feed in feeds
    }
    service = _FakeService(results)
    import app.services.feed_ingestion_service as fis

    monkeypatch.setattr(fis, "all_rss_feeds", lambda: feeds)
    monkeypatch.setattr(fis, "FeedIngestionService", lambda: service)
    monkeypatch.setattr(fis, "RSSFeed", SimpleNamespace)
    db = _FakeDB()
    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: db)
    # Sin Redis: el wrapper coalesce opera fail-open (documentado). En CI hay
    # Redis de verdad y un "ok" deja el claim 12 min: el siguiente test leia
    # "skipped" por contaminacion entre tests (run 40969459260). El coalesce
    # tiene su propia suite (test_coalesce_on_success.py); aqui se prueba el
    # actor.
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)
    service.db = db
    return service


def test_budget_exhaustion_defers_remaining_feeds(rss_env, monkeypatch):
    # t=0 arranque; t=10 primer feed ok; t=999 -> presupuesto agotado.
    monkeypatch.setattr(dramatiq_app, "time", _Clock([0.0, 10.0, 999.0]))
    monkeypatch.setattr(dramatiq_app, "_RSS_TIME_BUDGET_SECONDS", 480.0, raising=False)

    result = dramatiq_app.refresh_rss_feeds(tenant_id=10, user_id="u1")

    assert rss_env.polls == 1  # solo el primer feed llego a sondearse
    assert result["feeds_processed"] == 1
    assert result["status"] == "partial"
    budget_errors = [e for e in result["errors"] if e["type"] == "time_budget_exceeded"]
    assert len(budget_errors) == 1
    assert "3 feeds diferidos" in budget_errors[0]["message"]


def test_budget_already_exhausted_processes_nothing(rss_env, monkeypatch):
    monkeypatch.setattr(dramatiq_app, "time", _Clock([1000.0, 2000.0]))
    monkeypatch.setattr(dramatiq_app, "_RSS_TIME_BUDGET_SECONDS", 480.0, raising=False)

    result = dramatiq_app.refresh_rss_feeds(tenant_id=10, user_id="u1")

    assert rss_env.polls == 0
    assert result["feeds_processed"] == 0
    assert result["status"] == "error"
    assert result["errors"][0]["type"] == "time_budget_exceeded"
    assert "4 feeds diferidos" in result["errors"][0]["message"]


def test_within_budget_processes_every_feed(rss_env, monkeypatch):
    monkeypatch.setattr(dramatiq_app, "time", _Clock([0.0, 1.0, 2.0, 3.0, 4.0]))
    monkeypatch.setattr(dramatiq_app, "_RSS_TIME_BUDGET_SECONDS", 480.0, raising=False)

    result = dramatiq_app.refresh_rss_feeds(tenant_id=10, user_id="u1")

    assert rss_env.polls == 4
    assert result["status"] == "ok"
    assert result["feeds_processed"] == 4
    assert result["errors"] == []


def test_deferred_feeds_run_first_on_next_tick(rss_env, monkeypatch):
    """Hallazgo del piloto en #3029: sin cursor, cada tick empezaba por el
    feed 0 y bajo lentitud sostenida los ultimos feeds no corrian nunca.
    Con el orden por ultima sondeada (ConnectorState), los diferidos del
    tick 1 abren el tick 2."""
    feeds = rss_env.polled_urls  # se rellena al sondear

    # Tick 1: solo entra el primer feed; 3 diferidos.
    monkeypatch.setattr(dramatiq_app, "time", _Clock([0.0, 10.0, 999.0]))
    monkeypatch.setattr(dramatiq_app, "_RSS_TIME_BUDGET_SECONDS", 480.0, raising=False)
    r1 = dramatiq_app.refresh_rss_feeds(tenant_id=10, user_id="u1")
    assert r1["status"] == "partial"
    assert feeds == ["https://feed0.example/rss"]

    # Tick 2 (misma "BD"): entran dos mas y DEBEN ser los diferidos, no el 0.
    monkeypatch.setattr(dramatiq_app, "time", _Clock([0.0, 10.0, 20.0, 999.0]))
    r2 = dramatiq_app.refresh_rss_feeds(tenant_id=10, user_id="u1")
    assert r2["status"] == "partial"
    assert feeds[1:] == ["https://feed1.example/rss", "https://feed2.example/rss"]

    # Tick 3: el unico pendiente es el ultimo; el feed0 ya quedo a la cola.
    monkeypatch.setattr(dramatiq_app, "time", _Clock([0.0, 10.0, 999.0]))
    r3 = dramatiq_app.refresh_rss_feeds(tenant_id=10, user_id="u1")
    assert r3["status"] == "partial"
    assert feeds[3:] == ["https://feed3.example/rss"]
