"""Ramas de helpers puros: opt-out de ingesta por setting, clasificacion
transitorio/permanente (SEC 403 permanente, 429 acotado con breaker),
atribucion estructural a sec.gov, edad del mensaje, rachas GDELT,
single-flight, lease local/Redis y cuota diferida sin documento."""

import time
from types import SimpleNamespace

import dramatiq
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.core.database as coredb
from app.llm.errors import ProviderHTTPError, ProviderTransportError
from app.models import AlertRule, Company, Tenant, WatchItem
from app.models.entities import Base
from app.services.connectors.sec_pacing import SecQuotaDeferred
from app.workers import dramatiq_app as worker
from app.workers.rate_limit_retry import RateLimitRetriesExhausted


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.hashes = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    def expire(self, key, ttl):
        return True

    def hlen(self, key):
        return self.hashes.get(key, 0)

    def eval(self, *a, **k):
        return 1

    def close(self):
        pass


# --- _document_ingest_excluded ------------------------------------------------

def _exclusions(monkeypatch, raw):
    monkeypatch.setattr(worker, "settings",
                        SimpleNamespace(document_ingest_exclusions=raw))


def test_optout_global_por_ticker(monkeypatch):
    _exclusions(monkeypatch, ",,KRKNF,,OTHER,")
    assert worker._document_ingest_excluded(None, "krknf") is True
    assert worker._document_ingest_excluded(None, "ACME") is False


def test_optout_por_tenant_solo_en_su_cuenta(monkeypatch):
    _exclusions(monkeypatch, "10:KRKNF")
    assert worker._document_ingest_excluded(10, "KRKNF") is True
    assert worker._document_ingest_excluded(11, "KRKNF") is False
    assert worker._document_ingest_excluded(None, "KRKNF") is False


def test_optout_tenant_invalido_y_vacio(monkeypatch):
    _exclusions(monkeypatch, "abc:KRKNF")
    assert worker._document_ingest_excluded(10, "KRKNF") is False
    _exclusions(monkeypatch, "")
    assert worker._document_ingest_excluded(10, "KRKNF") is False


# --- _is_transient / _is_sec_failure ------------------------------------------

def test_transitorio_cadena_llm():
    assert worker._is_transient(ProviderTransportError("go", "timeout", 1)) is True
    assert worker._is_transient(ProviderHTTPError("go", 429)) is True
    assert worker._is_transient(ProviderHTTPError("go", 503)) is True
    assert worker._is_transient(ProviderHTTPError("go", 401)) is False


def test_transitorio_red_y_permanente_validacion():
    assert worker._is_transient(httpx.ConnectTimeout("t")) is True
    assert worker._is_transient(ValueError("payload roto")) is False


def test_sec_403_es_permanente_y_429_se_reintenta_acotado(monkeypatch):
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    e403 = RuntimeError("SEC EDGAR request failed (403 Forbidden) for url 'https://www.sec.gov/x'")
    assert worker._is_transient(e403) is False  # IP bloqueada: reintentar envenena la cola
    e429 = RuntimeError("SEC EDGAR request failed (429 Too Many Requests) for url 'https://www.sec.gov/x'")
    assert worker._is_transient(e429) is True  # con breaker compartido acotado


def test_sec_failure_atribucion_estructural():
    exc = httpx.ConnectError("corte", request=httpx.Request("GET", "https://efts.sec.gov/LATEST/x"))
    assert worker._is_sec_failure(exc) is True
    envuelto = RuntimeError("wrapper")
    envuelto.__cause__ = exc
    assert worker._is_sec_failure(envuelto) is True
    lookalike = httpx.ConnectError("corte", request=httpx.Request("GET", "https://sec.gov.evil.com/x"))
    assert worker._is_sec_failure(lookalike) is False
    assert worker._is_sec_failure(RuntimeError("sin pistas")) is False


def test_sec_failure_por_response_request():
    req = httpx.Request("GET", "https://data.sec.gov/submissions/CIK.json")
    exc = RuntimeError("fallo")
    exc.response = SimpleNamespace(request=req)
    assert worker._is_sec_failure(exc) is True


# --- mensaje en ejecucion -----------------------------------------------------

def _patch_message(monkeypatch, message):
    monkeypatch.setattr(worker.CurrentMessage, "get_current_message",
                        classmethod(lambda cls: message))


def test_edad_mensaje_sin_mensaje(monkeypatch):
    _patch_message(monkeypatch, None)
    assert worker._current_message_age_seconds() is None


def test_edad_mensaje_reintento_o_programado_no_cuenta(monkeypatch):
    _patch_message(monkeypatch, SimpleNamespace(options={"retries": 1}, message_timestamp=1))
    assert worker._current_message_age_seconds() is None


def test_edad_mensaje_primer_intento(monkeypatch):
    ts = (time.time() - 5) * 1000
    _patch_message(monkeypatch, SimpleNamespace(options={}, message_timestamp=ts))
    age = worker._current_message_age_seconds()
    assert 4.0 < age < 7.0


# --- rachas GDELT ---------------------------------------------------------------

def test_gdelt_429_redis_roto_no_abre():
    class BrokenRedis:
        def incr(self, key):
            raise ConnectionError("caido")

    assert worker._gdelt_429_recorded(BrokenRedis()) is False


def test_gdelt_429_racha_abre_disyuntor():
    redis = FakeRedis()
    redis.store[worker._GDELT_CIRCUIT_STREAK_KEY] = str(worker.GDELT_CIRCUIT_THRESHOLD - 1)
    assert worker._gdelt_429_recorded(redis) is True
    assert redis.get(worker._GDELT_CIRCUIT_KEY) == "1"


def test_gdelt_trip_redis_roto_no_lanza():
    class BrokenRedis:
        def set(self, *a, **k):
            raise ConnectionError("caido")

        def delete(self, *a):
            raise ConnectionError("caido")

    worker._gdelt_circuit_trip(BrokenRedis())  # expira por TTL solo: no lanza


def test_status_desde_mensaje_patron_status():
    assert worker._status_from_message("upstream returned status 502 today") == 502
    assert worker._status_from_message("sin codigo") is None


# --- _single_flight --------------------------------------------------------------

def test_single_flight_solapado_salta_y_redis_roto_ejecuta(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(worker, "_redis_client", lambda: redis)
    redis.set("running:job-x", "otro-token")

    @worker._single_flight("job-x", 60)
    def job():
        return {"status": "ok"}

    assert job()["reason"] == "already_running"

    monkeypatch.setattr(worker, "_redis_client",
                        lambda: (_ for _ in ()).throw(ConnectionError("caido")))
    assert job() == {"status": "ok"}  # Redis caido es fail-open


# --- coalesced_send con key_parts ------------------------------------------------

def test_coalesced_con_key_parts_distingue_tenants(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(worker, "_redis_client", lambda: redis)
    sends = []
    actor = SimpleNamespace(
        actor_name="refresh_portfolio_moves",
        send=lambda *a, **k: sends.append(k) or SimpleNamespace(message_id="m"))
    assert worker.coalesced_send(actor, tenant_id=1, user_id="u") is not None
    assert worker.coalesced_send(actor, tenant_id=2, user_id="u") is not None
    assert worker.coalesced_send(actor, tenant_id=1, user_id="u") is None
    assert len(sends) == 2  # una copia en vuelo POR tenant


# --- _session: idioma no soportado no se hereda -----------------------------------

def test_session_idioma_no_soportado_no_se_hereda(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tenant(id=1, external_id="e1", name="t", metadata_={"language": "xx"}))
    db.commit()
    monkeypatch.setattr(coredb, "SessionLocal", lambda: db)
    out = worker._session(1, "u")
    assert "language" not in out.info


# --- carriles tracked: ramas ----------------------------------------------------

def test_tracked_symbol_vacio_se_salta():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.add(WatchItem(tenant_id=1, symbol=""))
    db.commit()
    assert worker._tracked_companies(db) == []


def test_price_tracked_regla_sobre_ya_seguida_sin_releer():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.add(Company(ticker="ACME", name="a", exchange="NASDAQ",
                   company_type="operating", valuation_model="standard"))
    db.commit()
    acme = db.query(Company).filter_by(ticker="ACME").one()
    db.add(WatchItem(tenant_id=1, symbol="ACME"))
    db.add(AlertRule(tenant_id=1, company_id=acme.id, name="r",
                     rule_type="price", active=True))
    db.commit()
    assert [c.ticker for c in worker._price_tracked_companies(db)] == ["ACME"]


# --- _handle_actor_error ------------------------------------------------------

def test_handle_error_cuota_sec_reprograma():
    with pytest.raises(dramatiq.Retry):
        worker._handle_actor_error("actor", SecQuotaDeferred(120.0))


def test_handle_error_429_agotado_ack_sin_dead_letter():
    out = worker._handle_actor_error(
        "actor", RateLimitRetriesExhausted("GDELT", 6, 6))
    assert out == {"status": "skipped", "actor": "actor",
                   "reason": "rate_limited_retries_exhausted"}


# --- kpi_queue_depth --------------------------------------------------------------

def test_kpi_queue_depth_sin_redis_y_con_redis(monkeypatch):
    # "Sin Redis" se simula: sin este parche el caso depende del entorno.
    # Con REDIS_URL apuntando a un Redis real alcanzable (suite del Piloto:
    # TEST_REDIS_EPHEMERAL=1), _redis_client() conecta y una cola VACIA
    # devuelve 0, no None (None = Redis no disponible, no cola vacia).
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    assert worker.kpi_queue_depth(None) is None


def test_kpi_queue_depth_con_redis_alcanzable_y_cola_vacia_es_cero(monkeypatch):
    # El caso del Piloto: Redis efimero real arriba, hashes aun no creados.
    # 0 es la respuesta correcta (la admission gate no debe frenar), y fijarlo
    # aqui evita que nadie "arregle" la funcion para devolver None.
    class EmptyRedis:
        def hlen(self, key):
            return 0

    monkeypatch.setattr(worker, "_redis_client", lambda: EmptyRedis())
    assert worker.kpi_queue_depth(None) == 0
    redis = FakeRedis()
    broker = dramatiq.get_broker()
    base = f"{broker.namespace}:{worker.KPI_QUEUE_NAME}"
    redis.hashes[f"{base}.msgs"] = 3
    redis.hashes[f"{base}.DQ.msgs"] = 1
    assert worker.kpi_queue_depth(redis) == 4

    class BrokenRedis:
        def hlen(self, key):
            raise ConnectionError("caido")

    assert worker.kpi_queue_depth(BrokenRedis()) is None


# --- leases locales y fallback Redis -------------------------------------------

def test_lease_local_excluye_y_libera():
    name = "job-local-a"
    token = worker.acquire_job_lease(name, ttl_seconds=600, redis_url=None)
    assert token is not None
    assert worker.acquire_job_lease(name, ttl_seconds=600, redis_url=None) is None
    worker.release_job_lease(name, "token-ajeno", redis_url=None)
    assert worker.acquire_job_lease(name, ttl_seconds=600, redis_url=None) is None
    worker.release_job_lease(name, token, redis_url=None)
    assert worker.acquire_job_lease(name, ttl_seconds=600, redis_url=None) is not None


def test_lease_redis_inalcanzable_cae_a_local():
    name = "job-local-b"
    url = "redis://localhost:9/0"  # puerto cerrado: fallback local documentado
    token = worker.acquire_job_lease(name, ttl_seconds=600, redis_url=url)
    assert token is not None
    assert worker.acquire_job_lease(name, ttl_seconds=600, redis_url=url) is None
    worker.release_job_lease(name, token, redis_url=url)
    assert worker.acquire_job_lease(name, ttl_seconds=600, redis_url=url) is not None


# --- extract_document_kpis: aplazos sin documento vivo -----------------------------

def test_aplazos_sin_documento_no_rompen(monkeypatch):
    import app.services.kpi_extraction_service as kes

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)

    from app.models import Document

    doc = Document(tenant_id=1, title="informe", source_type="filing", metadata_={})
    db.add(doc)
    db.commit()

    class DailyDeferred:
        async def extract_document(self, db_, document):
            from app.services.kpi_call_quota import KPIDailyDeferred

            db_.delete(document)  # borrado concurrente antes del re-get
            db_.flush()
            raise KPIDailyDeferred("cap")

    monkeypatch.setattr(kes, "KPIExtractionService", DailyDeferred)
    out = worker.extract_document_kpis.fn(doc.id, tenant_id=1, user_id="u")
    assert out["status"] == "deferred" and out["reason"] == "daily_call_limit"

    doc2 = Document(tenant_id=1, title="informe2", source_type="filing", metadata_={})
    db.add(doc2)
    db.commit()

    class PaymentRequired:
        async def extract_document(self, db_, document):
            db_.delete(document)
            db_.flush()
            raise ProviderHTTPError("go", 402)

    monkeypatch.setattr(kes, "KPIExtractionService", PaymentRequired)
    out = worker.extract_document_kpis.fn(doc2.id, tenant_id=1, user_id="u")
    assert out["status"] == "deferred" and out["reason"] == "provider_payment_required"


def test_knowledge_job_con_documento_borrado(monkeypatch):
    import app.services.knowledge_library_service as kls
    from app.models import ProcessingJob

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    monkeypatch.setattr(db, "close", lambda: None)
    db.add(ProcessingJob(tenant_id=1, job_type="knowledge_extraction",
                         entity_type="knowledge_document", entity_id=4242))
    db.commit()
    monkeypatch.setattr(kls, "KnowledgeLibraryService", object)
    out = worker.extract_knowledge_principles.fn(1, tenant_id=1, user_id="u")
    assert out["status"] == "error"
    assert "Knowledge document 4242" in out["error"]["message"]
