"""refresh_rss_feeds con sesion SQLite real: orden por ultima sondeada,
commit del cursor ANTES de sondear, presupuesto de tiempo y contabilidad
de errores. Solo se sustituye la red (poll_rss/ingest del servicio)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, ConnectorState
from app.services.feed_ingestion_service import RSSFeed
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)  # el test sigue usando la sesion
    e = SimpleNamespace(db=db, polls={}, poll_order=[], ingest_calls=[])

    class FakeService:
        async def poll_rss(self, url, ticker=None, source_label=None):
            e.poll_order.append(url)
            outcome = e.polls[url]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def ingest_news_result(self, db_, result, **kw):
            e.ingest_calls.append(kw)
            return {"created": 1}

    import app.services.feed_ingestion_service as fis

    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    monkeypatch.setattr(fis, "all_rss_feeds", lambda: e.feeds)
    e.feeds = []
    return e


def test_sin_feeds_devuelve_skipped(env):
    out = worker.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert out["status"] == "skipped" and out["reason"] == "RSS_FEEDS is empty"
    assert out["feeds_processed"] == 0


def _ok():
    return SimpleNamespace(errors=[], status="ok")


def test_orden_por_ultima_sondeada_y_cursor_commiteado(env):
    env.feeds = [RSSFeed("https://a.example.com/feed"), RSSFeed("https://b.example.com/feed")]
    env.polls = {f.url: _ok() for f in env.feeds}
    # A se sondeo hace nada; B nunca: B debe ir primero.
    env.db.add(ConnectorState(tenant_id=1, connector="rss", feed_url="https://a.example.com/feed",
                              last_started_at=datetime.now(UTC)))
    env.db.commit()
    out = worker.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert out["status"] == "ok" and out["feeds_processed"] == 2
    assert out["news_ingested"] == 2
    assert env.poll_order[0] == "https://b.example.com/feed"
    states = env.db.scalars(select(ConnectorState).where(ConnectorState.connector == "rss")).all()
    assert len(states) == 2 and all(s.last_started_at is not None for s in states)
    assert all(s.last_success_at is not None for s in states)


def test_error_en_un_feed_se_registra_y_el_resto_continua(env):
    env.feeds = [RSSFeed("https://a.example.com/feed"), RSSFeed("https://b.example.com/feed")]
    env.polls = {"https://a.example.com/feed": RuntimeError("boom"),
                 "https://b.example.com/feed": _ok()}
    out = worker.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert out["status"] == "partial" and out["feeds_processed"] == 1
    assert out["errors"][0]["type"] == "RuntimeError"
    state = env.db.scalar(select(ConnectorState).where(
        ConnectorState.feed_url == "https://a.example.com/feed"))
    assert state.consecutive_errors == 1 and state.last_error
    # last_started_at sobrevive al rollback: se commiteo antes de sondear.
    assert state.last_started_at is not None


def test_presupuesto_agotado_difiere_feeds(env, monkeypatch):
    monkeypatch.setattr(worker, "_RSS_TIME_BUDGET_SECONDS", 0.0)
    env.feeds = [RSSFeed("https://a.example.com/feed"), RSSFeed("https://b.example.com/feed")]
    env.polls = {f.url: _ok() for f in env.feeds}
    out = worker.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert out["feeds_processed"] == 0
    assert out["errors"][0]["type"] == "time_budget_exceeded"
    assert env.poll_order == []  # no se sondeo ninguno


def test_error_de_sesion_devuelve_payload_estructurado(env, monkeypatch):
    def boom(tenant, user):
        raise ValueError("sin base de datos")

    monkeypatch.setattr(worker, "_session", boom)
    env.feeds = [RSSFeed("https://a.example.com/feed")]
    out = worker.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["actor"] == "refresh_rss_feeds"


def test_carril_no_permitido_no_detecta_empresa(env):
    env.feeds = [RSSFeed("https://a.example.com/feed", lane="gobierno"),
                 RSSFeed("https://b.example.com/feed")]
    env.polls = {f.url: _ok() for f in env.feeds}
    worker.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    detect = {c["news_lane"]: c["detect_company"] for c in env.ingest_calls}
    assert detect == {"gobierno": False, None: True}


def test_resultado_con_errores_y_status_error_no_cuenta_procesado(env):
    env.feeds = [RSSFeed("https://a.example.com/feed")]
    env.polls = {"https://a.example.com/feed": SimpleNamespace(
        errors=["404", "parse"], status="error")}
    out = worker.refresh_rss_feeds.fn(tenant_id=1, user_id="u")
    assert out["feeds_processed"] == 0
    assert [e["message"] for e in out["errors"]] == ["404", "parse"]
    state = env.db.scalar(select(ConnectorState))
    assert state.last_success_at is None  # sin exito: el cursor sigue contando desde el inicio
