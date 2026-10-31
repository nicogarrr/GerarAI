"""Contrato del aislamiento de Redis en tests (cluster Backend quality 31-oct).

Backend quality corre xdist -n 2 contra un redis-server real. Sin aislamiento,
los claims coalesce:* / coalesce-enq:*, leases cavaai:*, el pacing global
(global_pacer:*) y los disyuntores (gdelt:circuit:*, sec_breaker:*) de un test
se comian al siguiente: la evaluacion DCA se saltaba con fresh_or_running
antes de llegar a sus monkeypatches (77 fallos).

El aislamiento es OPT-IN (TEST_REDIS_EPHEMERAL=1, lo pone el workflow de CI):
sin el no se borra nada ni se reasigna DB, porque APP_ENV=test no prueba que
el Redis sea desechable (conftest lo fija con setdefault) y un REDIS_URL
heredado apunta al stack de desarrollo. Estas pruebas necesitan Redis: en CI
lo instala el workflow; en local sin servidor se saltan.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

redis_sync = pytest.importorskip("redis")

from app.core.config import get_settings
from app.core.redis_retry import no_retry
from tests.conftest import (
    _TEST_REDIS_EPHEMERAL_VAR,
    _test_redis_ephemeral,
    _worker_redis_url,
    reset_shared_redis_dedup_state,
)


def _client():
    url = get_settings().redis_url
    if not url:
        pytest.skip("sin redis_url configurado")
    client = redis_sync.Redis.from_url(
        url, socket_connect_timeout=0.25, socket_timeout=0.5, retry=no_retry()
    )
    try:
        client.ping()
    except Exception:
        client.close()
        pytest.skip("sin Redis alcanzable (Backend quality lo instala en CI)")
    return client


def _requiere_opt_in():
    if not _test_redis_ephemeral():
        pytest.skip(f"sin opt-in {_TEST_REDIS_EPHEMERAL_VAR}=1 (lo pone el workflow de CI)")


def test_la_limpieza_borra_dedup_y_leases_y_respeta_lo_demas():
    _requiere_opt_in()
    client = _client()
    sufijo = uuid4().hex
    try:
        client.set(f"coalesce:test-aislamiento:{sufijo}", "token", ex=3600)
        client.set(f"coalesce-enq:test-aislamiento:{sufijo}", "token", ex=3600)
        client.set(f"cavaai:job-lease:test-aislamiento:{sufijo}", "token", ex=3600)
        client.set(f"otra:clave:{sufijo}", "intocable")

        reset_shared_redis_dedup_state()

        assert client.get(f"coalesce:test-aislamiento:{sufijo}") is None
        assert client.get(f"coalesce-enq:test-aislamiento:{sufijo}") is None
        assert client.get(f"cavaai:job-lease:test-aislamiento:{sufijo}") is None
        # La limpieza es quirurgica: nada de FLUSHDB.
        assert client.get(f"otra:clave:{sufijo}") == b"intocable"
        client.delete(f"otra:clave:{sufijo}")
    finally:
        client.close()


def test_sin_opt_in_no_se_borra_nada(monkeypatch):
    """Regresion de la revision del piloto: sin TEST_REDIS_EPHEMERAL=1 la
    limpieza es no-op aunque haya Redis alcanzable con claves de la app."""
    monkeypatch.delenv(_TEST_REDIS_EPHEMERAL_VAR, raising=False)
    client = _client()
    sufijo = uuid4().hex
    claves = [
        f"coalesce:test-aislamiento:{sufijo}",
        f"coalesce-enq:test-aislamiento:{sufijo}",
        f"cavaai:job-lease:test-aislamiento:{sufijo}",
        f"global_pacer:test-aislamiento:{sufijo}",
        f"gdelt:circuit:test-aislamiento:{sufijo}",
        f"sec_breaker:test-aislamiento:{sufijo}",
    ]
    try:
        for clave in claves:
            client.set(clave, "token", ex=3600)

        reset_shared_redis_dedup_state()

        for clave in claves:
            assert client.get(clave) == b"token", f"{clave} borrada sin opt-in"
    finally:
        client.delete(*claves)
        client.close()


def test_sin_opt_in_no_se_reasigna_db_por_worker(monkeypatch):
    """Sin opt-in, un REDIS_URL heredado no se reasigna a otra DB ni con xdist."""
    monkeypatch.delenv(_TEST_REDIS_EPHEMERAL_VAR, raising=False)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    assert _worker_redis_url() is None
    assert os.environ["REDIS_URL"] == "redis://localhost:6379/0"  # intacta


def test_con_opt_in_la_db_sigue_al_worker(monkeypatch):
    monkeypatch.setenv(_TEST_REDIS_EPHEMERAL_VAR, "1")
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    assert _worker_redis_url() == "redis://localhost:6379/1"
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    assert _worker_redis_url() == "redis://localhost:6379/0"
    # Sin xdist (mono-proceso) no se reasigna: db0 por defecto.
    monkeypatch.delenv("PYTEST_XDIST_WORKER")
    assert _worker_redis_url() is None


def test_cluster_dca_fresh_or_running_cerrado(monkeypatch):
    """Reproduce el fallo de CI y su cierre: con el claim ajeno presente la
    evaluacion se salta; tras el borde de limpieza el monkeypatch vuelve a mandar."""
    _requiere_opt_in()
    from app.workers import dramatiq_app

    client = _client()
    try:

        class FakeDb:
            info: dict = {}

            def commit(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr(dramatiq_app, "_session", lambda tenant_id, user_id: FakeDb())
        monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda name, **kw: None)

        # 1) El claim ajeno (ventana 20 h, lo dejo otro test) salta la evaluacion:
        # es exactamente el fallo de test_dca_actor_scheduler en CI.
        client.set("coalesce:evaluate_dca_signals:7", "token-ajeno", ex=20 * 3600)
        out = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
        assert out["reason"] == "fresh_or_running"

        # 2) El fixture autouse limpia ANTES de cada test: aqui se invoca a mano
        # para simular el borde entre tests.
        reset_shared_redis_dedup_state()

        # 3) La victima vuelve a llegar a su monkeypatch (lease_held).
        out = dramatiq_app.evaluate_dca_signals.fn(7, "u-1")
        assert out["reason"] == "lease_held"
    finally:
        client.delete("coalesce:evaluate_dca_signals:7")
        client.close()
