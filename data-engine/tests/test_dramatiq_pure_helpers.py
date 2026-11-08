"""Helpers puros de app.workers.dramatiq_app.

Sobre main (25.3% con los tests de workers) faltaban el disyuntor GDELT,
la rama de cuota SEC y de racha agotada de _handle_actor_error, los
helpers _current_message_*, coalesced_send, las sondas kpi_queue_*,
_document_ingest_excluded, _document_url_ingested, _tracked_companies /
_price_tracked_companies y el camino Redis de acquire/release_job_lease.
Redis, el broker y el mensaje en curso sustituidos por dobles: sin red
ni LLM.
"""
from __future__ import annotations

import inspect
import time
from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.workers.rate_limit_retry as rate_limit_retry
from app.models import AlertRule, Company, Document, Position, WatchItem
from app.models.entities import Base
from app.services.connectors.sec_pacing import SecQuotaDeferred
from app.workers import dramatiq_app as mod


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.info["tenant_id"] = 1
        yield db
    engine.dispose()


class _FakeRedis:
    """Doble minimo de Redis para las sondas (dict en memoria)."""

    def __init__(self):
        self.store = {}
        self.hashes = {}

    def exists(self, key):
        return key in self.store

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    def expire(self, key, ttl):
        return True

    def hlen(self, key):
        return self.hashes.get(key, 0)

    def eval(self, script, nkeys, key, token):
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0

    def close(self):
        pass


class _ExplodingRedis:
    """Redis caido: cualquier operacion lanza (sondas fail-open)."""

    def __getattr__(self, name):
        raise RuntimeError("redis caido")


def _company(db, ticker: str) -> Company:
    company = Company(
        ticker=ticker,
        name=f"{ticker} Corp",
        exchange="BME",
        company_type="bank",
        valuation_model="dividend",
    )
    db.add(company)
    db.commit()
    return company


# --- disyuntor GDELT --------------------------------------------------------


def test_gdelt_circuit_open_fail_open_sin_redis():
    assert mod._gdelt_circuit_open(None) is False
    assert mod._gdelt_circuit_open(_ExplodingRedis()) is False


def test_gdelt_racha_abre_el_disyuntor_al_umbral():
    client = _FakeRedis()
    assert mod._gdelt_429_recorded(None) is False
    assert mod._gdelt_429_recorded(client) is False
    assert mod._gdelt_429_recorded(client) is False
    # Tercer 429 seguido: se abre el disyuntor y se resetea la racha.
    assert mod._gdelt_429_recorded(client) is True
    assert mod._gdelt_circuit_open(client) is True
    assert mod._GDELT_CIRCUIT_STREAK_KEY not in client.store


def test_gdelt_exito_rompe_la_racha_y_sondas_no_lanzan():
    client = _FakeRedis()
    mod._gdelt_429_recorded(client)
    mod._gdelt_success_recorded(client)
    assert mod._gdelt_circuit_open(client) is False
    # Best-effort: con Redis caido ninguna sonda propaga la excepcion.
    mod._gdelt_success_recorded(_ExplodingRedis())
    mod._gdelt_circuit_trip(_ExplodingRedis())
    assert mod._gdelt_429_recorded(_ExplodingRedis()) is False


def test_raise_gdelt_retry_con_disyuntor_abierto_espera_al_menos_el_ttl(monkeypatch):
    monkeypatch.setattr(mod, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(mod, "_gdelt_429_recorded", lambda client: True)
    captured = {}

    def _retry_or_drop(name, *, base, cap, retry_after):
        captured.update(base=base, cap=cap, retry_after=retry_after)
        raise dramatiq.Retry("reintenta", delay=1000)

    monkeypatch.setattr(rate_limit_retry, "retry_or_drop", _retry_or_drop)
    with pytest.raises(dramatiq.Retry):
        mod._raise_gdelt_retry(Exception("429"))
    assert captured["base"] == float(mod.GDELT_CIRCUIT_TTL_SECONDS)
    assert captured["cap"] == captured["base"]
    # Sin ventana del servidor, el suelo es el TTL del disyuntor.
    assert captured["retry_after"] == captured["base"]


def test_retry_jitter_dentro_de_la_cota():
    for _ in range(50):
        assert 0 <= mod._retry_jitter_ms(500) <= 500


# --- _handle_actor_error -----------------------------------------------------


def test_handle_actor_error_cuota_sec_difiere_con_retry():
    with pytest.raises(dramatiq.Retry) as excinfo:
        mod._handle_actor_error("actor", SecQuotaDeferred(retry_after=12.3))
    assert excinfo.value.delay == 12300


def test_handle_actor_error_racha_agotada_es_skipped_sin_dead_letter():
    out = mod._handle_actor_error(
        "actor", rate_limit_retry.RateLimitRetriesExhausted("GDELT", retries=6, max_retries=6)
    )
    assert out == {
        "status": "skipped",
        "actor": "actor",
        "reason": "rate_limited_retries_exhausted",
    }


# --- atribucion SEC con URL rota ---------------------------------------------


def test_is_sec_failure_url_inaccesible_no_es_sec():
    class _Url:
        @property
        def host(self):
            raise RuntimeError("url rota")

    exc = Exception("fallo")
    exc.request = SimpleNamespace(url=_Url())
    assert mod._is_sec_failure(exc) is False


# --- introspeccion del mensaje en curso --------------------------------------


class _FakeMessage:
    def __init__(self, options=None, timestamp=None):
        self.options = options or {}
        self.message_timestamp = timestamp


def _current_message(monkeypatch, message):
    monkeypatch.setattr(
        mod.CurrentMessage,
        "get_current_message",
        classmethod(lambda cls: message),
    )


def test_current_message_sin_evidencia_es_tick_nuevo(monkeypatch):
    _current_message(monkeypatch, None)
    assert mod._current_message_is_retry_or_delayed() is False
    assert mod._current_message_retries() == 0
    assert mod._current_message_age_seconds() is None


def test_current_message_sonda_rota_es_fail_open(monkeypatch):
    def _boom(cls):
        raise RuntimeError("middleware roto")

    monkeypatch.setattr(mod.CurrentMessage, "get_current_message", classmethod(_boom))
    assert mod._current_message_is_retry_or_delayed() is False
    assert mod._current_message_retries() == 0
    assert mod._current_message_age_seconds() is None


def test_current_message_reintento_o_diferido_nunca_obsoleto(monkeypatch):
    _current_message(monkeypatch, _FakeMessage(options={"retries": 2}))
    assert mod._current_message_is_retry_or_delayed() is True
    assert mod._current_message_retries() == 2
    assert mod._current_message_age_seconds() is None
    _current_message(monkeypatch, _FakeMessage(options={"eta": 123}))
    assert mod._current_message_is_retry_or_delayed() is True


def test_current_message_retries_malformados_cuentan_cero(monkeypatch):
    _current_message(monkeypatch, _FakeMessage(options={"retries": "abc"}))
    assert mod._current_message_retries() == 0


def test_current_message_edad_del_tick_nuevo(monkeypatch):
    ahora_ms = time.time() * 1000
    _current_message(monkeypatch, _FakeMessage(timestamp=ahora_ms - 5000))
    edad = mod._current_message_age_seconds()
    assert edad is not None and 4.0 <= edad <= 10.0
    _current_message(monkeypatch, _FakeMessage(timestamp=None))
    assert mod._current_message_age_seconds() is None


# --- coalesced_send -----------------------------------------------------------


class _FakeActor:
    def __init__(self, name="job_x"):
        self.actor_name = name
        self.sent = []

    def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return "msg"


def _registra_policy(monkeypatch, key_parts=()):
    def fn(a, b=2):
        return None

    monkeypatch.setitem(
        mod._COALESCE_POLICIES,
        "job_x",
        {
            "window": 60,
            "key_parts": key_parts,
            "stale_after": 60,
            "sig": inspect.signature(fn),
        },
    )


def test_coalesced_send_sin_politica_envia_siempre(monkeypatch):
    actor = _FakeActor(name="sin_policy")
    monkeypatch.setattr(mod, "_redis_client", lambda: _FakeRedis())
    assert mod.coalesced_send(actor, 1) == "msg"
    assert mod.coalesced_send(actor, 1) == "msg"
    assert len(actor.sent) == 2


def test_coalesced_send_una_copia_en_vuelo_por_clave(monkeypatch):
    _registra_policy(monkeypatch, key_parts=("a",))
    actor = _FakeActor()
    client = _FakeRedis()  # un solo cliente: la marca sobrevive entre llamadas
    monkeypatch.setattr(mod, "_redis_client", lambda: client)
    assert mod.coalesced_send(actor, 1) == "msg"
    assert mod.coalesced_send(actor, 1) is None  # duplicado suprimido
    assert mod.coalesced_send(actor, 2) == "msg"  # otra clave: envia
    assert len(actor.sent) == 2


def test_coalesced_send_fail_open_sin_redis(monkeypatch):
    _registra_policy(monkeypatch)
    actor = _FakeActor()
    monkeypatch.setattr(mod, "_redis_client", lambda: None)
    assert mod.coalesced_send(actor, 1) == "msg"
    monkeypatch.setattr(mod, "_redis_client", lambda: _ExplodingRedis())
    assert mod.coalesced_send(actor, 1) == "msg"


def test_coalesced_send_libera_la_marca_si_el_envio_falla(monkeypatch):
    _registra_policy(monkeypatch)
    client = _FakeRedis()
    monkeypatch.setattr(mod, "_redis_client", lambda: client)

    class _ActorQueFalla(_FakeActor):
        def send(self, *args, **kwargs):
            raise RuntimeError("broker caido")

    with pytest.raises(RuntimeError):
        mod.coalesced_send(_ActorQueFalla(), 1)
    # La marca se libero: un tick posterior puede reintentar.
    assert not client.store


# --- sondas de la cola KPI ----------------------------------------------------


def test_kpi_queue_depth_suma_listos_y_diferidos():
    client = _FakeRedis()
    base = f"{mod.broker.namespace}:{mod.KPI_QUEUE_NAME}"
    client.hashes[f"{base}.msgs"] = 3
    client.hashes[f"{base}.DQ.msgs"] = 2
    assert mod.kpi_queue_depth(client) == 5
    assert mod.kpi_queue_depth(_ExplodingRedis()) is None


def test_kpi_queue_has_capacity_respeta_el_tope(monkeypatch):
    monkeypatch.setattr(mod, "kpi_queue_max_pending", lambda: 4)
    monkeypatch.setattr(mod, "kpi_queue_depth", lambda client=None: 3)
    assert mod.kpi_queue_has_capacity() is True
    monkeypatch.setattr(mod, "kpi_queue_depth", lambda client=None: 4)
    assert mod.kpi_queue_has_capacity() is False
    monkeypatch.setattr(mod, "kpi_queue_depth", lambda client=None: None)
    assert mod.kpi_queue_has_capacity() is False  # fail-closed


def test_kpi_defer_lease_seconds_suelo_y_defecto(monkeypatch):
    monkeypatch.delenv("KPI_DEFER_LEASE_SECONDS", raising=False)
    assert mod.kpi_defer_lease_seconds() == 900
    monkeypatch.setenv("KPI_DEFER_LEASE_SECONDS", "30")
    assert mod.kpi_defer_lease_seconds() == 60  # suelo
    monkeypatch.setenv("KPI_DEFER_LEASE_SECONDS", "no-es-numero")
    assert mod.kpi_defer_lease_seconds() == 900


# --- exclusiones y dedup de ingesta ------------------------------------------


def test_document_ingest_excluded_global_y_por_tenant(monkeypatch):
    monkeypatch.setattr(mod.settings, "document_ingest_exclusions", "")
    assert mod._document_ingest_excluded(None, "KRKNF") is False
    monkeypatch.setattr(mod.settings, "document_ingest_exclusions", "krknf")
    assert mod._document_ingest_excluded(None, "KRKNF") is True
    monkeypatch.setattr(mod.settings, "document_ingest_exclusions", "10:ACME, x:ACME, 11:TEF")
    assert mod._document_ingest_excluded(10, "acme") is True
    assert mod._document_ingest_excluded(11, "ACME") is False
    assert mod._document_ingest_excluded(5, "ACME") is False  # "x:ACME" se ignora
    assert mod._document_ingest_excluded(11, "TEF") is True
    assert mod._document_ingest_excluded(None, "TEF") is False


def test_document_url_ingested_dedup_en_encolado(db):
    db.add(Document(tenant_id=1, title="t", source_type="url", source_url="https://x/a"))
    db.commit()
    assert mod._document_url_ingested(db, "https://x/a") is True
    assert mod._document_url_ingested(db, "https://x/otra") is False


# --- carriles tracked de precios y noticias -----------------------------------


def test_tracked_companies_cartera_y_watchlist_con_alias(db):
    san = _company(db, "SAN")
    ibe = _company(db, "IBE")
    _company(db, "TEF")  # no seguida
    db.add(Position(tenant_id=1, company_id=san.id, quantity=1))
    db.add(WatchItem(tenant_id=1, symbol="ibe.mc"))
    db.commit()
    assert [c.ticker for c in mod._tracked_companies(db)] == ["IBE", "SAN"]


def test_price_tracked_companies_anade_reglas_activas(db):
    san = _company(db, "SAN")
    tef = _company(db, "TEF")
    db.add(Position(tenant_id=1, company_id=san.id, quantity=1))
    db.add(
        AlertRule(
            tenant_id=1, company_id=tef.id, name="r", rule_type="price", active=True
        )
    )
    db.commit()
    assert [c.ticker for c in mod._price_tracked_companies(db)] == ["SAN", "TEF"]


# --- leases distribuidos -------------------------------------------------------


def test_lease_camino_redis_acquire_y_release(monkeypatch):
    import redis as redis_sync

    client = _FakeRedis()
    monkeypatch.setattr(
        redis_sync.Redis, "from_url", staticmethod(lambda url, **kw: client)
    )
    token = mod.acquire_job_lease("job-r", ttl_seconds=60, redis_url="redis://fake")
    assert token
    # Mismo job en vuelo: el segundo worker no entra.
    assert mod.acquire_job_lease("job-r", ttl_seconds=60, redis_url="redis://fake") is None
    # Compare-and-del: un token ajeno no borra el lease.
    mod.release_job_lease("job-r", "token-ajeno", redis_url="redis://fake")
    assert client.store
    mod.release_job_lease("job-r", token, redis_url="redis://fake")
    assert not client.store


def test_lease_redis_caido_hace_fallback_local(monkeypatch):
    import redis as redis_sync

    def _boom(url, **kw):
        raise RuntimeError("sin redis")

    monkeypatch.setattr(redis_sync.Redis, "from_url", staticmethod(_boom))
    try:
        token = mod.acquire_job_lease("job-local", redis_url="redis://fake")
        assert token
        assert mod.acquire_job_lease("job-local", redis_url="redis://fake") is None
        mod.release_job_lease("job-local", token, redis_url="redis://fake")
        assert mod.acquire_job_lease("job-local", redis_url="redis://fake")
    finally:
        mod.reset_local_leases()


def test_lease_redis_url_y_reset_local(monkeypatch):
    monkeypatch.setattr(
        mod, "get_settings", lambda: SimpleNamespace(redis_url="redis://x")
    )
    assert mod._lease_redis_url() == "redis://x"

    def _boom():
        raise RuntimeError("sin settings")

    monkeypatch.setattr(mod, "get_settings", _boom)
    assert mod._lease_redis_url() is None
    mod._local_leases["j"] = ("t", time.time() + 10)
    mod.reset_local_leases()
    assert not mod._local_leases


# --- puente async ----------------------------------------------------------------


def test_run_delega_en_el_puente_compartido(monkeypatch):
    import app.services.async_bridge as bridge

    async def _coro():
        return 1

    coro = _coro()
    monkeypatch.setattr(bridge, "run_from_any_context", lambda c: "ok")
    assert mod._run(coro) == "ok"
    coro.close()
