"""Contrato del aislamiento de Redis en tests (cluster Backend quality 31-oct).

Backend quality corre xdist -n 2 contra un redis-server real. Sin aislamiento,
los claims coalesce:* / coalesce-enq:* y los leases cavaai:* de un test se
comian al siguiente: la evaluacion DCA se saltaba con fresh_or_running antes
de llegar a sus monkeypatches (77 fallos). Estas pruebas necesitan Redis: en
CI lo instala el workflow; en local sin servidor se saltan.
"""

from __future__ import annotations

import pytest

redis_sync = pytest.importorskip("redis")

from app.core.config import get_settings
from app.core.redis_retry import no_retry
from tests.conftest import reset_shared_redis_dedup_state


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


def test_la_limpieza_borra_dedup_y_leases_y_respeta_lo_demas():
    client = _client()
    try:
        client.set("coalesce:evaluate_dca_signals:7", "token-ajeno", ex=20 * 3600)
        client.set("coalesce-enq:evaluate_dca_signals:7", "token-ajeno", ex=24 * 3600)
        client.set("cavaai:job-lease:dca_eval", "token-ajeno", ex=3600)
        client.set("otra:clave", "intocable")

        reset_shared_redis_dedup_state()

        assert client.get("coalesce:evaluate_dca_signals:7") is None
        assert client.get("coalesce-enq:evaluate_dca_signals:7") is None
        assert client.get("cavaai:job-lease:dca_eval") is None
        # La limpieza es quirurgica: nada de FLUSHDB.
        assert client.get("otra:clave") == b"intocable"
        client.delete("otra:clave")
    finally:
        client.close()


def test_cluster_dca_fresh_or_running_cerrado(monkeypatch):
    """Reproduce el fallo de CI y su cierre: con el claim ajeno presente la
    evaluacion se salta; tras el borde de limpieza el monkeypatch vuelve a mandar."""
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
