"""backfill_finnhub_profiles: cooldown 429 compartido y reencolado tras la ventana.

Antes del fix el backfill de perfiles no miraba el cooldown 429 compartido
de Finnhub ni cortaba la corrida: hasta 600 llamadas contra la ventana
cerrada (300 empresas x quote+profile) contadas como "error" de transporte
y resultado "ok". Ahora:

- cooldown vigente al entrar: dramatiq.Retry con la ventana (o skipped si
  los reintentos estan agotados: el cron de manana retoma, sin dead-letter);
- 429 a mitad de pasada: el servicio devuelve partial/finnhub_429 y el
  actor reencola el resto tras la ventana; lo procesado lleva Document y
  no se repite;
- la sesion se cierra en todos los caminos (antes no se cerraba nunca).
"""
from __future__ import annotations

from unittest.mock import Mock

import dramatiq
import pytest

from app.services import finnhub_profile_backfill as backfill_module
from app.services.connectors import finnhub as finnhub_connector
from app.workers import dramatiq_app as worker
from app.workers import rate_limit_retry


@pytest.fixture()
def env(monkeypatch):
    db = Mock(name="db")
    monkeypatch.setattr(worker, "_session", lambda tenant_id, user_id: db)
    monkeypatch.setattr(worker, "_retry_jitter_ms", lambda *a, **k: 0)
    result_holder = {"result": {"status": "ok", "procesadas": 7}}

    class _FakeService:
        def __init__(self):
            self.closed = False

        def backfill(self, db, *, max_companies=300):
            return result_holder["result"]

        def close(self):
            self.closed = True

    monkeypatch.setattr(backfill_module, "FinnhubProfileBackfill", _FakeService)
    monkeypatch.setattr(finnhub_connector, "finnhub_blocked_for", lambda: 0.0)
    monkeypatch.setattr(rate_limit_retry, "retries_exhausted", lambda: False)
    return {"db": db, "result": result_holder}


def test_cooldown_vigente_reencola_tras_la_ventana(env, monkeypatch):
    monkeypatch.setattr(finnhub_connector, "finnhub_blocked_for", lambda: 45.0)
    with pytest.raises(dramatiq.Retry) as caught:
        worker.backfill_finnhub_profiles(tenant_id=1, user_id="u")
    assert caught.value.delay == 45_000
    # Ni sesion ni servicio: cero llamadas contra la ventana cerrada.
    env["db"].close.assert_not_called()


def test_cooldown_vigente_con_reintentos_agotados_no_va_a_dead_letter(env, monkeypatch):
    monkeypatch.setattr(finnhub_connector, "finnhub_blocked_for", lambda: 45.0)
    monkeypatch.setattr(rate_limit_retry, "retries_exhausted", lambda: True)
    out = worker.backfill_finnhub_profiles(tenant_id=1, user_id="u")
    assert out == {
        "status": "skipped",
        "actor": "backfill_finnhub_profiles",
        "reason": "rate_limited_retries_exhausted",
    }


def test_429_a_mitad_reencola_el_resto_tras_la_ventana(env):
    env["result"]["result"] = {
        "status": "partial",
        "reason": "finnhub_429",
        "retry_after_seconds": 90.0,
        "procesadas": 2,
        "pendientes_tras_run": 3,
    }
    with pytest.raises(dramatiq.Retry) as caught:
        worker.backfill_finnhub_profiles(tenant_id=1, user_id="u")
    assert caught.value.delay == 90_000
    env["db"].close.assert_called()  # la sesion ya no se queda abierta


def test_429_a_mitad_con_reintentos_agotados_devuelve_parcial(env, monkeypatch):
    monkeypatch.setattr(rate_limit_retry, "retries_exhausted", lambda: True)
    env["result"]["result"] = {
        "status": "partial",
        "reason": "finnhub_429",
        "retry_after_seconds": 90.0,
        "procesadas": 2,
        "pendientes_tras_run": 3,
    }
    out = worker.backfill_finnhub_profiles(tenant_id=1, user_id="u")
    assert out["status"] == "partial"
    assert out["reason"] == "finnhub_429"
    assert out["procesadas"] == 2
    env["db"].close.assert_called()


def test_corrida_ok_devuelve_el_resultado_y_cierra_sesion(env):
    out = worker.backfill_finnhub_profiles(tenant_id=1, user_id="u")
    assert out == {"actor": "backfill_finnhub_profiles", "status": "ok", "procesadas": 7}
    env["db"].close.assert_called()


def test_skipped_por_cooldown_en_servicio_no_reintenta(env):
    """El servicio tambien mira el cooldown (defensa en profundidad): un
    skipped por cooldown no merece Retry porque ya no gasto ni una llamada."""
    env["result"]["result"] = {
        "status": "skipped",
        "reason": "finnhub_cooldown_429",
        "blocked_for_seconds": 45,
        "procesadas": 0,
    }
    out = worker.backfill_finnhub_profiles(tenant_id=1, user_id="u")
    assert out["status"] == "skipped"
    assert out["reason"] == "finnhub_cooldown_429"
    env["db"].close.assert_called()


def test_finnhub_pacer_expone_el_singleton_compartido():
    """El backfill sync y los carriles async reservan el MISMO hueco global."""
    from app.services.connectors.finnhub import _pacer, finnhub_pacer

    assert finnhub_pacer() is _pacer
