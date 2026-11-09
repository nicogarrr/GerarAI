"""Bordes del watchdog de colas: guards de env, watched_queues y emit.

Complementa tests/test_queue_watchdog.py (que cubre la logica Redis con
fakeredis) con las guardas puras que quedaban sin cubrir: valores por
defecto, parseo y fallback ValueError de los cuatro umbrales de entorno,
la seleccion de colas vigiladas (env > broker > lista estatica), la
muestra previa corrupta y las guardas de entrada de emit.
"""

from __future__ import annotations

import pytest

from app.services import queue_watchdog as wd


@pytest.fixture
def redis_client():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeRedis(decode_responses=False)


# --- guards de env: defecto, parseo, clamp y fallback ValueError ----------


def test_env_helpers_defecto_sin_variables(monkeypatch):
    for var in (
        "QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS",
        "QUEUE_WATCHDOG_MAX_AGE_SECONDS",
        "QUEUE_WATCHDOG_HARD_MAX_AGE_SECONDS",
        "QUEUE_WATCHDOG_WORKER_HEARTBEAT_TIMEOUT_MS",
    ):
        monkeypatch.delenv(var, raising=False)
    assert wd.max_sample_gap_seconds() == 600.0
    assert wd.max_age_seconds() == 900.0
    assert wd.hard_max_age_seconds() == 14400.0
    assert wd.worker_heartbeat_timeout_ms() == 60000.0


def test_env_helpers_parseo_y_clamp(monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "120")
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "30")
    monkeypatch.setenv("QUEUE_WATCHDOG_HARD_MAX_AGE_SECONDS", "60")
    monkeypatch.setenv("QUEUE_WATCHDOG_WORKER_HEARTBEAT_TIMEOUT_MS", "500")
    assert wd.max_sample_gap_seconds() == 120.0
    assert wd.max_age_seconds() == 60.0  # clamp al minimo 60
    assert wd.hard_max_age_seconds() == 300.0  # clamp al minimo 300
    assert wd.worker_heartbeat_timeout_ms() == 1000.0  # clamp al minimo 1000


def test_env_helpers_valor_no_numerico_cae_al_defecto(monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_SAMPLE_GAP_SECONDS", "no-numero")
    monkeypatch.setenv("QUEUE_WATCHDOG_MAX_AGE_SECONDS", "")
    monkeypatch.setenv("QUEUE_WATCHDOG_HARD_MAX_AGE_SECONDS", "mucho")
    monkeypatch.setenv("QUEUE_WATCHDOG_WORKER_HEARTBEAT_TIMEOUT_MS", "infinito!")
    assert wd.max_sample_gap_seconds() == 600.0
    assert wd.max_age_seconds() == 900.0
    assert wd.hard_max_age_seconds() == 14400.0
    assert wd.worker_heartbeat_timeout_ms() == 60000.0


# --- watched_queues: env > broker > lista estatica -------------------------


def test_watched_queues_env_gana_con_espacios_y_vacios(monkeypatch):
    monkeypatch.setenv("QUEUE_WATCHDOG_QUEUES", " prices , kpis ,,")
    assert wd.watched_queues() == ("prices", "kpis")


def test_watched_queues_env_solo_comas_cae_al_broker(monkeypatch):
    class Broker:
        def get_declared_queues(self):
            return ["zeta", "alpha"]  # lista desordenada: el servicio ordena

    monkeypatch.setenv("QUEUE_WATCHDOG_QUEUES", " , ,")
    assert wd.watched_queues(Broker()) == ("alpha", "zeta")  # ordenadas


def test_watched_queues_broker_sin_colas_cae_a_la_estatica(monkeypatch):
    class Broker:
        def get_declared_queues(self):
            return set()

    monkeypatch.delenv("QUEUE_WATCHDOG_QUEUES", raising=False)
    assert wd.watched_queues(Broker()) == wd.DEFAULT_QUEUES


def test_watched_queues_broker_roto_avisa_y_cae_a_la_estatica(monkeypatch, caplog):
    class Broker:
        def get_declared_queues(self):
            raise RuntimeError("broker caido")

    monkeypatch.delenv("QUEUE_WATCHDOG_QUEUES", raising=False)
    with caplog.at_level("WARNING", logger="app.services.queue_watchdog"):
        assert wd.watched_queues(Broker()) == wd.DEFAULT_QUEUES
    assert "no se pudieron listar las colas declaradas" in caplog.text


# --- load_previous: muestra corrupta = primera vez -------------------------


def test_load_previous_json_corrupto_devuelve_none(redis_client):
    redis_client.set(f"{wd._SAMPLE_PREFIX}prices", "no-es-json")
    assert wd.load_previous(redis_client, "prices") is None


def test_load_previous_sin_claves_devuelve_none(redis_client):
    redis_client.set(f"{wd._SAMPLE_PREFIX}prices", "[1, 2]")
    assert wd.load_previous(redis_client, "prices") is None


# --- emit: guardas de entrada ----------------------------------------------


def _make_db_sin_tenant():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.models.entities import Base

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_emit_sin_tenant_en_sesion_lanza_value_error():
    session = _make_db_sin_tenant()
    try:
        with pytest.raises(ValueError, match="Tenant context required"):
            wd.emit_queue_stuck_alerts(session)
    finally:
        session.close()


def test_emit_con_broker_real_usa_sus_colas_declaradas(redis_client, monkeypatch):
    import app.workers.dramatiq_app as dapp

    # La env gana al broker en watched_queues: hay que limpiarla o el recuento
    # de colas medido no es el de las declaradas.
    monkeypatch.delenv("QUEUE_WATCHDOG_QUEUES", raising=False)

    class Broker:
        namespace = "dramatiq"

        def get_declared_queues(self):
            return {"prices"}

    monkeypatch.setattr(dapp, "_redis_client", lambda: redis_client)
    monkeypatch.setattr(dapp, "broker", Broker())
    session = _make_db_sin_tenant()
    session.info["tenant_id"] = 1
    try:
        stats = wd.emit_queue_stuck_alerts(session, now=wd.datetime(2026, 11, 9, 12, 0, tzinfo=wd.UTC))
    finally:
        session.close()
    assert stats["status"] == "ok"
    assert stats["queues"] == 1  # solo la cola declarada del broker
    assert stats["sampled"] is True
