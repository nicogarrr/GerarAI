"""Pruebas del latido del planificador (quien vigila al vigilante).

Motivo (medido 18-nov-2026): los watchdogs in-app los dispara el
planificador; si muere, todo queda en silencio y parece sano.

Expected Behavior:
- Cada job que termina BIEN graba scheduler:heartbeat:<job_id> (ISO UTC) en
  Redis via listener EVENT_JOB_EXECUTED; el listener se registra en
  build_scheduler y solo escucha ejecuciones exitosas (un job fallido no late)
- La escritura es fail-open: Redis caido o set fallido = warning + False,
  nunca una excepcion que rompa el job
- Fakes minimos de scheduler sin add_listener no rompen build_scheduler

Run from data-engine/:
    pytest tests/test_scheduler_heartbeat.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import app.workers.scheduler as sched
from app.services import scheduler_heartbeat as hb


class FakeRedis:
    """Cliente minimo: captura set y puede fallar a pedido."""

    def __init__(self, *, fail: bool = False):
        self.writes: dict[str, str] = {}
        self.fail = fail

    def set(self, key, value):
        if self.fail:
            raise ConnectionError("redis caido (fake)")
        self.writes[key] = value


def test_record_escribe_clave_e_iso_utc():
    fake = FakeRedis()
    instante = datetime(2026, 11, 18, 23, 58, 0, tzinfo=UTC)
    hb.record(fake, "queue_watchdog", now=instante)
    assert fake.writes == {
        "scheduler:heartbeat:queue_watchdog": "2026-11-18T23:58:00+00:00"
    }
    # El valor se parsea de vuelta al mismo instante (lo lee date -d en el host).
    assert datetime.fromisoformat(
        fake.writes["scheduler:heartbeat:queue_watchdog"]) == instante


def test_record_job_ok_devuelve_true(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(hb, "_client_for", lambda url: fake)
    assert hb.record_job("db_connection_watchdog",
                         redis_url="redis://fake:6379/0") is True
    assert "scheduler:heartbeat:db_connection_watchdog" in fake.writes


def test_record_job_sin_cliente_es_failopen(monkeypatch):
    def roto(url):
        raise ConnectionError("sin redis (fake)")

    monkeypatch.setattr(hb, "_client_for", roto)
    assert hb.record_job("queue_watchdog",
                         redis_url="redis://fake:6379/0") is False


def test_record_job_set_fallido_es_failopen(monkeypatch):
    monkeypatch.setattr(hb, "_client_for",
                        lambda url: FakeRedis(fail=True))
    assert hb.record_job("source_freshness_watchdog",
                         redis_url="redis://fake:6379/0") is False


def test_client_for_cachea_por_url(monkeypatch):
    creados = []

    class FakeFactory:
        @staticmethod
        def from_url(url, **kw):
            creados.append((url, kw))
            return FakeRedis()

    monkeypatch.setitem(__import__("sys").modules, "redis", FakeFactory)
    monkeypatch.setattr(hb, "_clients", {})
    a = hb._client_for("redis://a:6379/0")
    b = hb._client_for("redis://a:6379/0")
    c = hb._client_for("redis://b:6379/0")
    assert a is b and c is not a
    assert len(creados) == 2  # una conexion por URL, no por latido


def test_listener_registrado_solo_en_ejecuciones_exitosas():
    """build_scheduler registra el latido sobre EVENT_JOB_EXECUTED: un job
    fallido no escribe latido, y el chequeo del host acaba alertando."""
    registrado = {}

    class Fake:
        def add_job(self, func, trigger, id=None, **kw):
            pass

        def add_listener(self, callback, mask):
            registrado["callback"] = callback
            registrado["mask"] = mask

    with patch.object(sched, "BlockingScheduler", return_value=Fake()), patch.object(
            sched, "tenant_contexts", return_value=[]), patch(
            "app.workers.dramatiq_app._redis_client", return_value=None):
        sched.build_scheduler()

    from apscheduler.events import EVENT_JOB_EXECUTED

    assert registrado["mask"] == EVENT_JOB_EXECUTED
    with patch("app.services.scheduler_heartbeat.record_job") as rec:
        registrado["callback"](SimpleNamespace(job_id="queue_watchdog"))
    rec.assert_called_once_with("queue_watchdog")


def test_build_scheduler_sobrevive_a_fake_sin_add_listener():
    """Los fakes minimos de los tests de cadencia (sin add_listener) no
    rompen el registro de jobs."""

    class FakeMinimo:
        def __init__(self):
            self.jobs = 0

        def add_job(self, func, trigger, id=None, **kw):
            self.jobs += 1

    fake = FakeMinimo()
    with patch.object(sched, "BlockingScheduler", return_value=fake), patch.object(
            sched, "tenant_contexts", return_value=[]), patch(
            "app.workers.dramatiq_app._redis_client", return_value=None):
        sched.build_scheduler()
    assert fake.jobs > 0
