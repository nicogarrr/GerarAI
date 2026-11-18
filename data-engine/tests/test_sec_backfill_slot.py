"""backfill_sec_fundamentals no puede ocupar los dos hilos de la cola externa.

Medido por el Piloto (18-nov): cada mensaje dura 7,5-10,6 min; dos a la vez
ocupaban los 2 hilos de worker-externa y refresh_valuation_metrics esperaba.
Invariantes: (1) como mucho UNA corrida en vuelo con Redis disponible (fallback local
por proceso si falla);
(2) la copia que llega con el hueco ocupado no trabaja ni abre sesion: se
reencola con retardo y contador; (3) agotados los diferimientos se rinde sin
reencolar; (4) el hueco se libera siempre (exito, error, sesion rota);
(5) los timeouts del actor no cambian.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.workers import dramatiq_app as worker

SLOT = worker.SEC_BACKFILL_SLOT


@pytest.fixture(autouse=True)
def _aislado(monkeypatch):
    worker.reset_local_leases()
    monkeypatch.setattr(worker, "_redis_client", lambda: None)  # coalescencia fail-open
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)  # lease local
    monkeypatch.setattr(worker, "_retry_jitter_ms", lambda max_ms=30_000: 0)
    yield
    worker.reset_local_leases()


class _Db:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _stub(monkeypatch, run=None, session=None):
    calls: dict[str, Any] = {"sessions": [], "runs": [], "sends": []}
    db = _Db()

    def _session(tenant, user):
        calls["sessions"].append((tenant, user))
        if session is not None:
            raise session
        return db

    def _run(database, max_companies):
        calls["runs"].append((database, max_companies, SLOT in worker._local_leases))
        if run is not None:
            raise run
        return {"status": "ok", "processed": 3}

    monkeypatch.setattr(worker, "_session", _session)
    monkeypatch.setattr(worker, "_rollback", lambda d: None)
    monkeypatch.setattr(
        "app.services.sec_fundamentals_backfill.backfill_sec_fundamentals", _run
    )
    monkeypatch.setattr(
        worker.backfill_sec_fundamentals,
        "send_with_options",
        lambda **kw: calls["sends"].append(kw),
    )
    calls["db"] = db
    return calls


def _call(**kw):
    return worker.backfill_sec_fundamentals.fn(tenant_id=7, user_id="u", **kw)


def test_con_hueco_libre_trabaja_dentro_del_hueco_y_lo_libera(monkeypatch):
    calls = _stub(monkeypatch)
    out = _call(max_companies=25)
    assert out["status"] == "ok"
    assert calls["runs"] == [(calls["db"], 25, True)]  # el hueco estaba tomado al correr
    assert SLOT not in worker._local_leases
    assert calls["db"].closed is True
    assert calls["sends"] == []


def test_con_hueco_ocupado_no_trabaja_ni_abre_sesion_y_se_reencola(monkeypatch):
    calls = _stub(monkeypatch)
    held = worker.acquire_job_lease(SLOT, ttl_seconds=60, redis_url=None)
    assert held is not None
    out = _call(max_companies=40)
    assert out["status"] == "skipped"
    assert out["reason"] == "slot_busy_deferred"
    assert calls["sessions"] == [] and calls["runs"] == []
    assert calls["sends"] == [
        {
            "kwargs": {"tenant_id": 7, "user_id": "u", "max_companies": 40, "deferrals": 1},
            "delay": worker.SEC_BACKFILL_DEFER_DELAY_MS,
        }
    ]
    assert out["deferrals"] == 1
    # El hueco ajeno sigue siendo del otro dueno.
    assert worker._local_leases[SLOT][0] == held


def test_el_diferimiento_libera_la_coalescencia_para_poder_reintentar(monkeypatch):
    # status "skipped" (no "ok"): el claim no queda como marca fresca.
    from tests.test_coalesce_on_success import FakeRedis

    redis = FakeRedis()
    monkeypatch.setattr(worker, "_redis_client", lambda: redis)
    calls = _stub(monkeypatch)
    worker.acquire_job_lease(SLOT, ttl_seconds=60, redis_url=None)
    out = worker.backfill_sec_fundamentals.fn(tenant_id=7, user_id="u")
    assert out["reason"] == "slot_busy_deferred"
    assert not [k for k in redis.store if k.startswith("coalesce:backfill_sec_fundamentals")]
    assert len(calls["sends"]) == 1


def test_diferimientos_agotados_se_rinde_sin_reencolar(monkeypatch):
    calls = _stub(monkeypatch)
    worker.acquire_job_lease(SLOT, ttl_seconds=60, redis_url=None)
    out = _call(deferrals=worker.SEC_BACKFILL_MAX_DEFERRALS)
    assert out["status"] == "skipped"
    assert out["reason"] == "slot_busy_deferrals_exhausted"
    assert calls["sends"] == []
    assert calls["runs"] == []


def test_ultimo_diferimiento_permitido_aun_reencola(monkeypatch):
    calls = _stub(monkeypatch)
    worker.acquire_job_lease(SLOT, ttl_seconds=60, redis_url=None)
    out = _call(deferrals=worker.SEC_BACKFILL_MAX_DEFERRALS - 1)
    assert out["reason"] == "slot_busy_deferred"
    assert calls["sends"][0]["kwargs"]["deferrals"] == worker.SEC_BACKFILL_MAX_DEFERRALS


def test_el_hueco_se_libera_si_la_ingesta_falla(monkeypatch):
    calls = _stub(monkeypatch, run=RuntimeError("boom"))
    out = _call()
    assert out["status"] == "error"
    assert SLOT not in worker._local_leases
    assert calls["db"].closed is True


def test_el_hueco_se_libera_si_la_sesion_falla(monkeypatch):
    calls = _stub(monkeypatch, session=ValueError("tenant inactivo"))
    out = _call()
    assert out["status"] == "error"
    assert SLOT not in worker._local_leases
    assert calls["runs"] == []


def test_dos_corridas_seguidas_no_se_bloquean_entre_si(monkeypatch):
    calls = _stub(monkeypatch)
    assert _call()["status"] == "ok"
    assert _call()["status"] == "ok"
    assert len(calls["runs"]) == 2 and calls["sends"] == []


def test_hueco_cubre_el_time_limit_y_los_timeouts_no_cambian():
    options = worker.backfill_sec_fundamentals.options
    assert options["time_limit"] == 1_800_000
    assert options["max_retries"] == 2
    assert options["time_limit"] < worker.SEC_BACKFILL_SLOT_TTL_SECONDS * 1000
    assert worker.backfill_sec_fundamentals.queue_name == "externa"


def test_antes_dos_corridas_simultaneas_ocupaban_los_dos_hilos_ahora_solo_una(monkeypatch):
    """Medida del fallo: dos hilos del mismo worker, ambos con mensaje de
    backfill. Con el tope, el segundo no entra mientras el primero corre."""
    import threading

    calls = _stub(monkeypatch)
    dentro = threading.Event()
    soltar = threading.Event()
    en_vuelo = {"now": 0, "max": 0}
    lock = threading.Lock()

    def lenta(database, max_companies):
        with lock:
            en_vuelo["now"] += 1
            en_vuelo["max"] = max(en_vuelo["max"], en_vuelo["now"])
        dentro.set()
        soltar.wait(5)
        with lock:
            en_vuelo["now"] -= 1
        return {"status": "ok"}

    monkeypatch.setattr("app.services.sec_fundamentals_backfill.backfill_sec_fundamentals", lenta)
    resultados = []
    primero = threading.Thread(target=lambda: resultados.append(_call()))
    primero.start()
    assert dentro.wait(5)
    segundo = worker.backfill_sec_fundamentals.fn(tenant_id=8, user_id="v")
    soltar.set()
    primero.join(5)
    assert segundo["reason"] == "slot_busy_deferred"
    assert en_vuelo["max"] == 1
    assert resultados[0]["status"] == "ok"
    assert calls["sends"][0]["kwargs"]["tenant_id"] == 8


def test_el_retardo_lleva_jitter_para_no_reintentar_todos_a_la_vez(monkeypatch):
    seen = []
    monkeypatch.setattr(
        worker, "_retry_jitter_ms", lambda max_ms=30_000: seen.append(max_ms) or 4_321
    )
    calls = _stub(monkeypatch)
    worker.acquire_job_lease(SLOT, ttl_seconds=60, redis_url=None)
    _call()
    assert seen == [worker.SEC_BACKFILL_DEFER_JITTER_MS]
    assert calls["sends"][0]["delay"] == worker.SEC_BACKFILL_DEFER_DELAY_MS + 4_321
