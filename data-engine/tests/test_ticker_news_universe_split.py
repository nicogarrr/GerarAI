"""Split universo US: una descarga global + persistencia por tenant via cache.

Contrato del fix del backlog Yahoo (9-nov-2026): la red se paga una vez por
ciclo (refresh_ticker_news_universe) y cada tenant etiqueta/ingiere su propio
universo desde la cache (persist_ticker_news_universe), con fail-open a red
en miss. Los contadores (llamadas de red, hits de cache) son la medicion:
nunca wall-clock.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.workers import dramatiq_app
from app.workers.queue_taxonomy import ACTOR_CLASS, INGESTA
from tests.test_coalesce_on_success import FakeRedis


def _fn(name: str):
    actor = getattr(dramatiq_app, name)
    return getattr(actor, "fn", actor)


class _Db:
    def __init__(self, tag=None) -> None:
        self.tag = tag

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeService:
    def __init__(self) -> None:
        self.polled: list[tuple[str, str]] = []
        self.ingested: list[str] = []
        self.fail_429: set[str] = set()
        self.fail_error: set[str] = set()

    async def poll_rss(self, url, ticker=None, max_items=30):
        self.polled.append((ticker, url))
        if ticker in self.fail_429:
            return ConnectorResult(source="rss", items=[], errors=["Client error '429 Too Many Requests' for url"])
        if ticker in self.fail_error:
            return ConnectorResult(source="rss", items=[], errors=["HTTP 404 not found"])
        return ConnectorResult(
            source="rss",
            items=[
                ConnectorItem(
                    source="rss",
                    # Titular que supera los filtros reales de label_yahoo: cita
                    # el nombre, no solo un prefijo-ticker pegado.
                    title="Apple sube un 5% trimestral",
                    url=f"https://example.test/{ticker}/1",
                    summary="",
                    ticker=ticker,
                )
            ],
        )

    def ingest_news_result(self, db, result, ticker=None, news_lane=None):
        self.ingested.append(ticker)
        return {"created": len(result.items)}


def _co(cid, ticker, exchange="NASDAQ", name=None):
    return SimpleNamespace(id=cid, ticker=ticker, exchange=exchange, name=name or f"{ticker} Inc")


def _env(monkeypatch, contexts, companies_by_tag):
    """Cableado comun: sesiones por contexto, Redis falso, red simulada."""
    service = _FakeService()
    redis = FakeRedis()
    sessions = {tag: _Db(tag) for _, tag in contexts}
    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: sessions[u])
    monkeypatch.setattr(dramatiq_app, "_rollback", lambda db: None)
    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: redis)
    monkeypatch.setattr(dramatiq_app, "_run", lambda coro: __import__("asyncio").run(coro))
    monkeypatch.setattr(dramatiq_app.time, "sleep", lambda s: None)
    monkeypatch.setattr(dramatiq_app, "tenant_contexts", lambda: contexts)
    monkeypatch.setattr(
        dramatiq_app, "_companies", lambda db, ticker=None: companies_by_tag[db.tag]
    )
    monkeypatch.setattr(
        "app.services.feed_ingestion_service.FeedIngestionService", lambda: service
    )
    return service, redis


def test_descarga_global_una_vez_y_encola_persistencia_por_tenant(monkeypatch):
    contexts = [(1, "a"), (2, "b")]
    companies = [_co(1, "AAPL"), _co(2, "MSFT"), _co(3, "SAN", exchange="BME")]
    service, _ = _env(monkeypatch, contexts, {"a": companies, "b": companies})
    sent = []
    monkeypatch.setattr(
        dramatiq_app,
        "coalesced_send",
        lambda actor, *a: sent.append((actor.actor_name, a)) or SimpleNamespace(message_id="m"),
    )
    out = _fn("refresh_ticker_news_universe")()
    assert out["status"] == "ok"
    # Red: una vez por ticker del universo US (SAN no cotiza en EEUU), NO por tenant.
    assert sorted(t for t, _ in service.polled) == ["AAPL", "MSFT"]
    assert out["universe"] == 2 and out["feeds_fetched"] == 2
    # Persistencia explicita por tenant.
    assert sent == [("persist_ticker_news_universe", (1, "a")),
                    ("persist_ticker_news_universe", (2, "b"))]
    assert [q["tenant_id"] for q in out["queued"]] == [1, 2]


def test_persistencia_desde_cache_sin_red(monkeypatch):
    contexts = [(1, "a")]
    service, redis = _env(monkeypatch, contexts, {"a": [_co(1, "AAPL", name="Apple Inc")]})
    # La descarga global ya cacheo el feed crudo.
    dramatiq_app._yahoo_universe_cache_set(
        redis,
        "AAPL",
        ConnectorResult(
            source="rss",
            items=[ConnectorItem(source="rss", title="Apple sube un 5% trimestral", url="https://example.test/a")],
        ),
    )
    out = _fn("persist_ticker_news_universe")(tenant_id=1, user_id="a")
    assert out["status"] == "ok"
    assert service.polled == []  # cero red
    assert service.ingested == ["AAPL"]
    assert out["cache_hits"] == 1 and out["live_fetches"] == 0
    assert out["news_ingested"] == 1


def test_persistencia_miss_de_cache_cae_a_red_y_cachea(monkeypatch):
    contexts = [(1, "a")]
    service, redis = _env(monkeypatch, contexts, {"a": [_co(1, "AAPL", name="Apple Inc")]})
    out = _fn("persist_ticker_news_universe")(tenant_id=1, user_id="a")
    assert out["status"] == "ok"
    assert [t for t, _ in service.polled] == ["AAPL"]
    assert out["cache_hits"] == 0 and out["live_fetches"] == 1
    # Segundo tenant (mismo ciclo): el miss ya se cacheo, no hay segunda descarga.
    contexts2 = [(2, "b")]
    monkeypatch.setattr(dramatiq_app, "tenant_contexts", lambda: contexts2)
    sessions2 = {"b": _Db("b")}
    monkeypatch.setattr(dramatiq_app, "_session", lambda t, u: sessions2[u])
    monkeypatch.setattr(dramatiq_app, "_companies", lambda db, ticker=None: [_co(9, "AAPL")])
    out2 = _fn("persist_ticker_news_universe")(tenant_id=2, user_id="b")
    assert [t for t, _ in service.polled] == ["AAPL"]  # sigue habiendo una sola llamada
    assert out2["cache_hits"] == 1 and out2["live_fetches"] == 0


def test_persistencia_respeta_universo_del_tenant(monkeypatch):
    """El tenant solo ingiere SU universo US: la cache de otros tickers no se usa."""
    contexts = [(1, "a")]
    service, redis = _env(
        monkeypatch, contexts, {"a": [_co(1, "SAN", exchange="BME")]}  # no cotiza en EEUU
    )
    dramatiq_app._yahoo_universe_cache_set(
        redis, "AAPL", ConnectorResult(source="rss", items=[ConnectorItem(source="rss", title="AAPL x")])
    )
    out = _fn("persist_ticker_news_universe")(tenant_id=1, user_id="a")
    assert out["status"] == "ok"
    assert service.polled == [] and service.ingested == []
    assert out["feeds_processed"] == 0


def test_descarga_global_truncada_marca_partial(monkeypatch):
    from app.services import ticker_news_lane

    contexts = [(1, "a")]
    _env(monkeypatch, contexts, {"a": [_co(1, "AAPL", name="Apple Inc")]})
    real = ticker_news_lane.Deadline
    monkeypatch.setattr(ticker_news_lane, "Deadline", lambda s: real(0))
    sent = []
    monkeypatch.setattr(
        dramatiq_app,
        "coalesced_send",
        lambda actor, *a: sent.append(a) or SimpleNamespace(message_id="m"),
    )
    out = _fn("refresh_ticker_news_universe")()
    # Un ciclo truncado NO se reporta ok (el coalescer soltaria el claim y el
    # siguiente tick repondria la descarga), pero los tenants se encolan igual.
    assert out["truncated"] is True and out["status"] == "partial"
    assert out["feeds_fetched"] == 0
    assert sent == [(1, "a")]


def test_actores_nuevos_en_taxonomia_ingesta():
    assert ACTOR_CLASS.get("refresh_ticker_news_universe") == INGESTA
    assert ACTOR_CLASS.get("persist_ticker_news_universe") == INGESTA


def test_freno_abierto_a_mitad_de_ciclo_corta_sin_mas_llamadas(monkeypatch):
    """Test negativo del auditor: tras el primer 429 el freno se abre y el
    bucle NO hace mas llamadas (el viejo carril filtraba is_open por unidad)."""
    from app.services import provider_brake

    contexts = [(1, "a")]
    companies = [_co(i, t) for i, t in enumerate(["AAPL", "JNJ", "MSFT", "NVDA", "XOM"], 1)]
    service, redis = _env(monkeypatch, contexts, {"a": companies})
    service.fail_429.add("JNJ")  # segundo del orden alfabetico

    def _record_429_abre(client, provider):
        client.set(provider_brake._open_key(provider), "1", ex=60)
        return True

    monkeypatch.setattr(provider_brake, "record_429", _record_429_abre)
    sent = []
    monkeypatch.setattr(
        dramatiq_app,
        "coalesced_send",
        lambda actor, *a: sent.append(a) or SimpleNamespace(message_id="m"),
    )
    out = _fn("refresh_ticker_news_universe")()
    # Se descargan AAPL y JNJ (el 429) y NADA mas: MSFT/NVDA/XOM nunca se llaman.
    assert [t for t, _ in service.polled] == ["AAPL", "JNJ"]
    assert out["feeds_fetched"] == 1 and out["status"] == "partial"
    assert any("freno abierto" in e["message"] for e in out["errors"])
    # Los tenants se encolan igual: ingieren lo cacheado (AAPL) y el hueco
    # lo repone el siguiente ciclo.
    assert sent == [(1, "a")]
    assert dramatiq_app._yahoo_universe_cache_get(redis, "AAPL") is not None
    assert dramatiq_app._yahoo_universe_cache_get(redis, "MSFT") is None


def test_feed_con_error_no_se_cachea_y_persistencia_reintenta(monkeypatch):
    contexts = [(1, "a")]
    companies = [_co(1, "AAPL", name="Apple Inc"), _co(2, "MSFT")]
    service, redis = _env(monkeypatch, contexts, {"a": companies})
    service.fail_error.add("MSFT")  # 404: error de feed, no de cuota
    monkeypatch.setattr(
        dramatiq_app, "coalesced_send", lambda actor, *a: SimpleNamespace(message_id="m")
    )
    out = _fn("refresh_ticker_news_universe")()
    assert out["status"] == "partial"  # 1 ok + 1 error
    assert dramatiq_app._yahoo_universe_cache_get(redis, "AAPL") is not None
    assert dramatiq_app._yahoo_universe_cache_get(redis, "MSFT") is None  # error NO cacheado
    # La persistencia reintenta en vivo solo el feed sin cache (fail-open).
    service.fail_error.clear()
    out2 = _fn("persist_ticker_news_universe")(tenant_id=1, user_id="a")
    assert out2["cache_hits"] == 1 and out2["live_fetches"] == 1
    assert [t for t, _ in service.polled] == ["AAPL", "MSFT", "MSFT"]


def test_redis_caido_fail_open(monkeypatch):
    """Sin Redis: la descarga global trabaja igual y cada persistencia cae a
    la red por miss (comportamiento previo al split), sin romperse."""
    contexts = [(1, "a")]
    service, redis = _env(monkeypatch, contexts, {"a": [_co(1, "AAPL", name="Apple Inc")]})
    redis.raises = True  # FakeRedis(raises=True): set/get/eval lanzan
    monkeypatch.setattr(
        dramatiq_app, "coalesced_send", lambda actor, *a: SimpleNamespace(message_id="m")
    )
    out = _fn("refresh_ticker_news_universe")()
    assert out["status"] == "ok" and out["feeds_fetched"] == 1
    out2 = _fn("persist_ticker_news_universe")(tenant_id=1, user_id="a")
    assert out2["status"] == "ok"
    assert out2["live_fetches"] == 1 and out2["cache_hits"] == 0
    assert service.ingested == ["AAPL"]


def test_tenant_sin_tickers_us_no_trabaja(monkeypatch):
    contexts = [(1, "a")]
    service, _ = _env(monkeypatch, contexts, {"a": [_co(1, "SAN", exchange="BME")]})
    monkeypatch.setattr(
        dramatiq_app, "coalesced_send", lambda actor, *a: SimpleNamespace(message_id="m")
    )
    out = _fn("refresh_ticker_news_universe")()
    assert out["status"] == "ok" and out["universe"] == 0 and service.polled == []
    out2 = _fn("persist_ticker_news_universe")(tenant_id=1, user_id="a")
    assert out2["status"] == "ok" and out2["feeds_processed"] == 0
    assert service.polled == [] and service.ingested == []


def test_cache_roundtrip_preserva_payload():
    """Paridad de payload: el resultado reconstruido desde cache conserva
    todos los campos del item, los errores y la metadata (mas la marca de hit)."""
    from datetime import UTC, datetime

    redis = FakeRedis()
    original = ConnectorResult(
        source="rss",
        items=[
            ConnectorItem(
                source="rss",
                title="Apple sube un 5% trimestral",
                url="https://example.test/aapl/1",
                summary="Resumen del articulo",
                published_at=datetime(2026, 11, 9, 12, 30, tzinfo=UTC),
                ticker="AAPL",
                item_type="news",
                external_id="ext-1",
                headline_from_source=True,
                metadata={"news_lane": "ticker"},
            )
        ],
        errors=["aviso parcial"],
        metadata={"feed": "yahoo"},
    )
    dramatiq_app._yahoo_universe_cache_set(redis, "aapl", original)
    cached = dramatiq_app._yahoo_universe_cache_get(redis, "AAPL")
    assert cached is not None
    assert cached.source == original.source and cached.errors == original.errors
    assert cached.metadata == {"feed": "yahoo", "ticker_news_cache": "hit"}
    item, orig = cached.items[0], original.items[0]
    assert item.as_dict() | {"headline_from_source": item.headline_from_source} == (
        orig.as_dict() | {"headline_from_source": orig.headline_from_source}
    )
