"""refresh_ticker_news: frenos de proveedor (429) que pausan el barrido o el
carril, etiquetado por carril con ingest por tandas, errores por feed sin
tumbar el barrido."""

import dataclasses
import time
from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.company_alias_sources as cas
import app.services.feed_ingestion_service as fis
import app.services.provider_brake as brake
import app.services.ticker_news_lane as lane_mod
from app.models import Company
from app.models.entities import Base
from app.services.connectors.base import ConnectorResult
from app.workers import dramatiq_app as worker


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    open_brakes = set()
    calls_429, calls_ok = [], []
    monkeypatch.setattr(brake, "is_open", lambda client, p: p in open_brakes)
    monkeypatch.setattr(brake, "record_429", lambda client, p: calls_429.append(p))
    monkeypatch.setattr(brake, "record_success", lambda client, p: calls_ok.append(p))
    monkeypatch.setattr(cas, "ensure_aliases", lambda db_, companies, max_fetch: {})
    monkeypatch.setattr(cas, "search_terms", lambda record, company_name: ())
    polls = []
    outcomes = {}

    class FakeService:
        async def poll_rss(self, url, *, ticker, max_items):
            polls.append(url)
            outcome = outcomes.get(url)
            if isinstance(outcome, Exception):
                raise outcome
            if outcome is not None:
                return outcome
            return ConnectorResult(source="rss", items=[f"i-{len(polls)}"])

        def ingest_news_result(self, db_, part, *, ticker, news_lane=None):
            return {"created": len(part.items)}

    def fake_label(result, company, evidence, aliases=()):
        return dataclasses.replace(
            result, metadata={**result.metadata, "news_lane": "lane"})

    monkeypatch.setattr(fis, "FeedIngestionService", FakeService)
    monkeypatch.setattr(lane_mod, "label_yahoo", fake_label)
    monkeypatch.setattr(lane_mod, "label_google", fake_label)
    return SimpleNamespace(db=db, polls=polls, outcomes=outcomes,
                           open_brakes=open_brakes, calls_429=calls_429,
                           calls_ok=calls_ok)


def _company(db, ticker="ACME"):
    db.add(Company(ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ",
                   company_type="operating", valuation_model="standard"))
    db.commit()


def test_frenos_abiertos_sin_reintento_salta(env, monkeypatch):
    env.open_brakes.update(("yahoo", "google-news"))
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: False)
    out = worker.refresh_ticker_news.fn(tenant_id=1, user_id="u", ticker="ACME")
    assert out == {"status": "skipped", "actor": "refresh_ticker_news",
                   "reason": "provider_brakes_open"}


def test_frenos_abiertos_con_reintento_reprograma(env, monkeypatch):
    env.open_brakes.update(("yahoo", "google-news"))
    monkeypatch.setattr(worker, "_current_message_is_retry_or_delayed", lambda: True)
    with pytest.raises(dramatiq.Retry):
        worker.refresh_ticker_news.fn(tenant_id=1, user_id="u", ticker="ACME")


def test_barrido_ok_yahoo_y_google_con_alias_failopen(env):
    _company(env.db)
    out = worker.refresh_ticker_news.fn(tenant_id=1, user_id="u", ticker="ACME")
    assert out["status"] == "ok" and out["actor"] == "refresh_ticker_news"
    assert out["feeds_processed"] == 2  # yahoo + google-en (sin marcas: sin datos)
    assert out["news_ingested"] == 2
    assert len(env.polls) == 2
    assert set(env.calls_ok) == {"yahoo", "google-news"}


def test_429_de_yahoo_alimenta_el_freno(env):
    _company(env.db)
    env.outcomes[lane_mod.yahoo_feed_url("ACME")] = ConnectorResult(
        source="rss", errors=["Client error '429 Too Many Requests' for url"])
    out = worker.refresh_ticker_news.fn(tenant_id=1, user_id="u", ticker="ACME")
    assert "yahoo" in env.calls_429
    assert "google-news" not in env.calls_429
    assert out["status"] == "partial"  # el feed roto se anota, google sigue


def test_carril_pausado_ni_se_intenta(env):
    _company(env.db)
    env.open_brakes.add("yahoo")
    out = worker.refresh_ticker_news.fn(tenant_id=1, user_id="u", ticker="ACME")
    assert all("yahoo" not in url for url in env.polls)
    assert out["feeds_processed"] == 1  # solo google


def test_feed_roto_no_tumba_el_barrido(env):
    _company(env.db)
    env.outcomes[lane_mod.yahoo_feed_url("ACME")] = ValueError("xml roto")
    out = worker.refresh_ticker_news.fn(tenant_id=1, user_id="u", ticker="ACME")
    assert out["status"] == "partial"
    assert out["errors"][0]["source"] == "yahoo"
    assert out["feeds_processed"] == 1


def test_error_de_sesion_devuelve_payload(env, monkeypatch):
    monkeypatch.setattr(worker, "_session",
                        lambda t, u: (_ for _ in ()).throw(RuntimeError("pool")))
    out = worker.refresh_ticker_news.fn(tenant_id=1, user_id="u", ticker="ACME")
    assert out["status"] == "error" and out["actor"] == "refresh_ticker_news"
