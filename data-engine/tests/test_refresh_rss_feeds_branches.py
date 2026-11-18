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
    monkeypatch.setattr(
        fis,
        "RSSFeed",
        lambda url, ticker=None: SimpleNamespace(url=url, ticker=ticker, label=None, lane=None),
    )
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


class _CountingDB(_FakeDB):
    """_FakeDB que cuenta commits, cierre y guarda lo commiteado en cada commit."""

    def __init__(self):
        super().__init__()
        self.commits = 0
        self.closed = False
        self.committed_errors = []

    def commit(self):
        self.commits += 1
        self.committed_errors.append({s.feed_url: s.last_error for s in self.states})

    def close(self):
        self.closed = True


def _use_counting_db(monkeypatch):
    db = _CountingDB()
    rollbacks = []
    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: db)
    monkeypatch.setattr(dramatiq_app, "_rollback", lambda d: rollbacks.append(d))
    return db, rollbacks


def test_excepcion_hace_rollback_y_commitea_el_error(env, monkeypatch):
    db, rollbacks = _use_counting_db(monkeypatch)
    first = env.feeds[0].url

    def boom(_db, result, **kwargs):
        raise RuntimeError("fallo ingesta")

    env.ingest_news_result = boom

    dramatiq_app.refresh_rss_feeds.fn(tenant_id=1, user_id="u", feed_url=first)

    assert rollbacks == [db]  # un rollback, sobre la sesion
    # 1 commit previo al sondeo + 1 que persiste el error
    assert db.commits == 2
    assert db.committed_errors[-1][first] == "fallo ingesta"
    assert db.committed_errors[0][first] is None


def test_la_sesion_se_cierra_en_exito_y_en_excepcion(env, monkeypatch):
    db, _ = _use_counting_db(monkeypatch)
    dramatiq_app.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert db.closed is True

    db2, _ = _use_counting_db(monkeypatch)

    def boom(_db, result, **kwargs):
        raise RuntimeError("x")

    env.ingest_news_result = boom
    dramatiq_app.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert db2.closed is True


def test_error_externo_pasa_contexto_a_handle_actor_error(env, monkeypatch):
    seen = {}

    def fake_handle(actor_name, exc, **ctx):
        seen.update(actor=actor_name, exc=exc, ctx=ctx)
        return {"status": "error", "actor": actor_name}

    def fail(tenant_id, user_id):
        raise ValueError("sin sesion")

    monkeypatch.setattr(dramatiq_app, "_session", fail)
    monkeypatch.setattr(dramatiq_app, "_handle_actor_error", fake_handle)

    dramatiq_app.refresh_rss_feeds.fn(tenant_id=7, user_id="u", feed_url="https://f.example/rss", ticker="aapl")

    assert seen["actor"] == "refresh_rss_feeds"
    assert isinstance(seen["exc"], ValueError)
    assert seen["ctx"] == {
        "tenant_id": 7,
        "user_id": "u",
        "feed_url": "https://f.example/rss",
        "ticker": "aapl",
    }
