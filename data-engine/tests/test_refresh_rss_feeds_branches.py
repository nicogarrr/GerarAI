"""refresh_rss_feeds: ramas del actor sin test directo.

test_refresh_rss_time_budget cubre el presupuesto de tiempo; aqui se fijan el resto de
caminos del cuerpo:
- sin feeds configurados: skipped/"RSS_FEEDS is empty", sin abrir sesion;
- un feed que devuelve errores propios (status error) no cuenta como procesado, deja el
  error en el resultado y NO marca last_success_at;
- una excepcion al ingerir un feed: se registra en su ConnectorState (consecutive_errors,
  last_error con secretos redactados) y los demas feeds siguen (partial);
- un fallo permanente de _session sale estructurado, no crudo.

Run from data-engine/:
    pytest tests/test_refresh_rss_feeds_branches.py -v
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.feed_ingestion_service as fis
from app.workers import dramatiq_app
from tests.test_refresh_rss_time_budget import _FakeDB, _FakeService


def _feeds(n=2):
    return [
        SimpleNamespace(url=f"https://feed{i}.example/rss", ticker=None, label=None, lane=None)
        for i in range(n)
    ]


@pytest.fixture
def env(monkeypatch):
    feeds = _feeds(2)
    results = {f.url: SimpleNamespace(errors=[], status="ok", items=[]) for f in feeds}
    service = _FakeService(results)
    service.feeds = feeds
    service.results = results
    monkeypatch.setattr(fis, "all_rss_feeds", lambda: feeds)
    monkeypatch.setattr(fis, "FeedIngestionService", lambda: service)
    monkeypatch.setattr(fis, "RSSFeed", SimpleNamespace)
    db = _FakeDB()
    service.db = db
    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: db)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: None)  # coalescencia fail-open
    return service


def test_sin_feeds_configurados_skipped_sin_abrir_sesion(env, monkeypatch):
    monkeypatch.setattr(fis, "all_rss_feeds", lambda: [])
    opened = []
    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: opened.append(t))

    out = dramatiq_app.refresh_rss_feeds.fn(tenant_id=1, user_id="u")

    assert out == {
        "status": "skipped",
        "actor": "refresh_rss_feeds",
        "reason": "RSS_FEEDS is empty",
        "feeds_processed": 0,
    }
    assert opened == []


def test_feed_con_errores_propios_no_cuenta_como_procesado(env):
    bad = env.feeds[0]
    env.results[bad.url] = SimpleNamespace(errors=["HTTP 503"], status="error", items=[])

    out = dramatiq_app.refresh_rss_feeds.fn(tenant_id=1, user_id="u")

    assert out["feeds_processed"] == 1  # solo el feed sano
    assert out["status"] == "partial"
    assert {"url": bad.url, "source": "rss", "message": "HTTP 503"} in out["errors"]
    states = {s.feed_url: s for s in env.db.states}
    assert states[bad.url].last_success_at is None
    assert states[env.feeds[1].url].last_success_at is not None
    assert states[env.feeds[1].url].consecutive_errors == 0


def test_excepcion_al_ingerir_se_registra_en_el_estado_y_el_resto_sigue(env, monkeypatch):
    first = env.feeds[0].url
    original = env.ingest_news_result

    def ingest(db, result, **kwargs):
        if env.polled_urls[-1] == first:
            raise RuntimeError("fallo token=SECRETO123 al ingerir")
        return original(db, result, **kwargs)

    env.ingest_news_result = ingest
    monkeypatch.setattr(dramatiq_app, "redact_secrets", lambda text: text.replace("SECRETO123", "***"))

    out = dramatiq_app.refresh_rss_feeds.fn(tenant_id=1, user_id="u")

    assert env.polls == 2  # el segundo feed se sondeo igualmente
    assert out["feeds_processed"] == 1
    assert out["status"] == "partial"
    err = [e for e in out["errors"] if e["url"] == first][0]
    assert err["type"] == "RuntimeError"
    state = {s.feed_url: s for s in env.db.states}[first]
    assert state.consecutive_errors == 1
    assert "SECRETO123" not in state.last_error
    assert "***" in state.last_error


def test_error_permanente_de_sesion_sale_estructurado(env, monkeypatch):
    def fail(tenant_id, user_id):
        raise ValueError("tenant inactivo")

    monkeypatch.setattr(dramatiq_app, "_session", fail)

    out = dramatiq_app.refresh_rss_feeds.fn(tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert out["actor"] == "refresh_rss_feeds"
    assert env.polls == 0
