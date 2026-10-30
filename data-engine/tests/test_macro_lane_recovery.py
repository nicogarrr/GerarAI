"""Recuperación del carril macro: feeds oficiales de reserva, disyuntor
GDELT, dedupe entre tenants por cache y fallback de archivo en la API.

Contexto (medido en prod 30-oct-2026): GDELT inalcanzable desde la VM
(HTTP 000/429 sostenido), 0 eventos macro en 72h, cola gdelt con backlog.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import dramatiq
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import news as news_module
from app.core.database import get_db
from app.models.entities import Base, NewsEvent, Tenant
from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.feed_ingestion_service import MACRO_RSS_FEEDS, all_rss_feeds
from app.workers import dramatiq_app

NOW = datetime.now(UTC).replace(microsecond=0)


# ---------- feeds oficiales de reserva ----------

def test_macro_feeds_oficiales_en_carril_macro():
    assert len(MACRO_RSS_FEEDS) >= 2
    for feed in MACRO_RSS_FEEDS:
        assert feed.lane == "macro"
        assert feed.ticker is None  # fail-closed: nunca se vincula a empresa
        assert feed.label and feed.label.endswith("(oficial)")
    urls = [feed.url for feed in all_rss_feeds()]
    assert len(urls) == len(set(urls))  # sin duplicados
    for feed in MACRO_RSS_FEEDS:
        assert feed.url in urls


# ---------- disyuntor y dedupe del actor ----------

class _FakeRedis:
    """Redis mínimo en memoria (get/setex) para la cache de lotes."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


class _FakeMacroDB:
    def rollback(self):
        pass

    def close(self):
        pass


class _FakeMacroService:
    def __init__(self, *, error: Exception | None = None, items=None):
        self.polls = 0
        self.ingests = 0
        self._error = error
        self._items = items or []

    async def poll_gdelt(self, query, *, ticker=None, max_records=15):
        self.polls += 1
        if self._error is not None:
            raise self._error
        return ConnectorResult(source="gdelt", items=list(self._items))

    def ingest_news_result(self, db, result, **kwargs):
        self.ingests += 1
        return {"created": len(result.items)}


@pytest.fixture
def macro_env(monkeypatch):
    import app.services.feed_ingestion_service as fis

    db = _FakeMacroDB()
    monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: db)
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: object())
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: None)
    holder: dict = {}

    def _install(service, redis_client=None):
        monkeypatch.setattr(fis, "FeedIngestionService", lambda: service)
        monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: redis_client)
        holder["service"] = service

    return _install


def test_circuit_breaker_aborta_tras_dos_fallos(macro_env):
    service = _FakeMacroService(error=TimeoutError("GDELT timeout"))
    macro_env(service)
    result = dramatiq_app.refresh_macro_news(tenant_id=3, user_id="u1")
    # 2 fallos seguidos y se abre el disyuntor: no se queman las 13 consultas.
    assert service.polls == 2
    assert service.ingests == 0
    assert result["status"] == "error"
    assert any(e["type"] == "circuit_open" for e in result["errors"])


def test_429_tipado_sigue_reencolando(macro_env):
    from app.services.connectors.gdelt import GdeltRateLimited

    service = _FakeMacroService(error=GdeltRateLimited(120))
    macro_env(service)
    with pytest.raises(dramatiq.Retry):
        dramatiq_app.refresh_macro_news(tenant_id=3, user_id="u1")
    assert service.polls == 1  # reencola el lote tras la ventana, no sigue


def test_cache_dedup_entre_tenants(macro_env):
    item = ConnectorItem(source="gdelt", title="Oro al alza", url="https://x.example/1")
    redis_client = _FakeRedis()
    service_a = _FakeMacroService(items=[item])
    macro_env(service_a, redis_client)
    result_a = dramatiq_app.refresh_macro_news(tenant_id=3, user_id="u1")
    assert result_a["status"] == "ok"
    polls_a = service_a.polls
    assert polls_a >= 1

    # Segundo tenant: mismas respuestas desde cache, cero llamadas a GDELT;
    # la ingesta por tenant sí corre (cada tenant persiste sus filas).
    service_b = _FakeMacroService(items=[item])
    macro_env(service_b, redis_client)
    result_b = dramatiq_app.refresh_macro_news(tenant_id=6, user_id="u2")
    assert service_b.polls == 0
    assert service_b.ingests == service_a.ingests
    assert result_b["status"] == "ok"


# ---------- fallback de archivo en la API ----------

def _client(rows):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    db.add(Tenant(id=1, external_id="t"))
    for row in rows:
        db.add(row)
    db.commit()
    app = FastAPI()
    app.include_router(news_module.router, prefix="/api/news")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _macro_row(title, date, url):
    return NewsEvent(tenant_id=1, company_id=None, title=title, source="GDELT",
                     url=url, date=date, metadata_={"news_lane": "macro", "macro_theme": "inflation"})


def test_macro_sin_frescura_sirve_archivo_marcado():
    old = _macro_row("Evento macro antiguo", NOW - timedelta(days=6), "https://p.example/old")
    body = _client([old]).get("/api/news", params={"lane": "macro"}).json()
    assert len(body) == 1
    assert body[0]["archive"] is True
    assert body[0]["title"] == "Evento macro antiguo"
    # La fecha real viaja: la UI nunca finge frescura.
    assert body[0]["date"].startswith((NOW - timedelta(days=6)).date().isoformat())


def test_macro_con_frescura_no_marca_archivo():
    fresh = _macro_row("Evento macro fresco", NOW - timedelta(hours=3), "https://p.example/fresh")
    old = _macro_row("Evento macro antiguo", NOW - timedelta(days=6), "https://p.example/old")
    body = _client([fresh, old]).get("/api/news", params={"lane": "macro"}).json()
    assert len(body) == 1  # el corte de 72h sigue aplicando cuando hay frescura
    assert body[0]["archive"] is False
    assert body[0]["title"] == "Evento macro fresco"


def test_archivo_no_aplica_a_otros_carriles():
    old = NewsEvent(tenant_id=1, company_id=None, title="Comunicado oficial antiguo",
                    source="Reserva Federal (oficial)", url="https://p.example/gov",
                    date=NOW - timedelta(days=6), metadata_={"news_lane": "gobierno"})
    body = _client([old]).get("/api/news", params={"lane": "gobierno"}).json()
    assert len(body) == 1
    assert body[0]["archive"] is False
