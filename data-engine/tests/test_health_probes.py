"""Readiness y health sin work bloqueante ni auto-envenenamiento.

Regresiones que fijan este fichero:
- /api/health es publico y lo consulta la orquestacion. Antes hacia un
  subprocess.run(git) (fork de 2 s), construia un APScheduler completo con 18
  jobs y ejecutaba SQL sincrono, todo en el event loop y en cada request.
- /health/ready compartia un unico ThreadPoolExecutor(4) entre 4 sondas: si
  Redis/Qdrant/MinIO aceptaban la conexion y no respondian, los 4 hilos quedaban
  ocupados y la sonda de BD ya no encontraba ninguno -> 503 permanente con la
  base de datos sana.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import main as main_module
from app.api.routes import health as health_module


def test_health_db_probe_runs_off_the_event_loop(monkeypatch):
    """El handler async no debe ejecutar SQL síncrono en el loop."""
    import threading

    calls: list[str] = []
    seen: dict[str, int] = {}

    def _probe_database() -> str:
        seen["thread"] = threading.get_ident()
        calls.append("db")
        return "ok"

    monkeypatch.setattr(health_module, "_probe_database", _probe_database)
    result = asyncio.run(health_module.health())
    loop_thread = threading.get_ident()

    assert result["database"] == "ok"
    assert calls == ["db"]
    assert seen["thread"] != loop_thread, "la sonda de BD se ejecutó en el event loop"


def test_health_does_not_spawn_git_per_request(monkeypatch):
    """_git_version está cacheado: no se paga un fork por request."""
    health_module._git_version.cache_clear()
    monkeypatch.setenv("APP_VERSION", "main-testver")
    try:
        assert health_module._git_version() == "main-testver"
        # Segunda llamada servida desde cache aunque el env cambie.
        monkeypatch.delenv("APP_VERSION")
        assert health_module._git_version() == "main-testver"
    finally:
        health_module._git_version.cache_clear()


def test_health_scheduler_job_count_is_cached(monkeypatch):
    health_module._scheduler_job_count.cache_clear()
    calls: list[int] = []

    class _FakeScheduler:
        def get_jobs(self):
            calls.append(1)
            return [object(), object()]

    import app.workers.scheduler as scheduler_module

    original = scheduler_module.build_scheduler
    scheduler_module.build_scheduler = lambda background=False: _FakeScheduler()
    # El suite apaga los workers; este test necesita la rama activada.
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(workers_enabled=True),
    )
    try:
        first = health_module._scheduler_status()
        second = health_module._scheduler_status()
    finally:
        scheduler_module.build_scheduler = original
        health_module._scheduler_job_count.cache_clear()

    assert first["jobs"] == 2
    assert second["jobs"] == 2
    assert len(calls) == 1, "el scheduler se reconstruyó en el segundo request"


def test_health_scheduler_external_is_unknown_not_stopped(monkeypatch):
    """F7: con WORKERS_ENABLED=false (scheduler en su servicio) no se afirma 'parado'."""
    monkeypatch.setattr(
        health_module,
        "get_settings",
        lambda: SimpleNamespace(workers_enabled=False),
    )
    status = health_module._scheduler_status()
    assert status["enabled"] is False
    assert status["running"] is None
    assert status["external"] is True
    assert "servicio aparte" in status["note"]


def test_prod_compose_passes_app_version_to_backend():
    """F7: sin APP_VERSION la API publica 'main-unknown' (la imagen no lleva git)."""
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.prod.yml").read_text()
    # El compose puede declarar environment como lista o como mapa (anchors).
    assert (
        "APP_VERSION=${APP_VERSION:-}" in compose
        or "APP_VERSION: ${APP_VERSION:-}" in compose
    )


def test_required_probe_has_its_own_executor():
    """La BD no puede quedarse sin hilo por culpa de las sondas opcionales."""
    required = main_module._HEALTH_REQUIRED_EXECUTOR._max_workers
    optional = main_module._HEALTH_PROBE_EXECUTOR._max_workers
    assert required >= 1
    assert optional >= 1
    # Y el wiring lo usa de verdad.
    import inspect

    source = inspect.getsource(main_module.health_ready)
    assert "_HEALTH_REQUIRED_EXECUTOR" in source


def test_ready_reports_ready_even_when_optional_probes_hang(monkeypatch):
    """Tres sondas opcionales colgadas no pueden degradar a 503 la ruta.

    Se reproducen las condiciones reales: el await vence su deadline, pero el
    hilo de la sonda sigue vivo y ocupa el worker.
    """
    import threading

    started = threading.Event()
    release = threading.Event()

    def _hang(_settings) -> str:
        started.set()
        release.wait(timeout=10)
        return "ok"

    # This regression isolates executor starvation, not database latency.
    # Keep the required probe on its real executor and prove it ran off-loop.
    required_threads: list[int] = []
    caller_thread = threading.get_ident()

    def _healthy_database(_settings) -> str:
        required_threads.append(threading.get_ident())
        return "ok"

    monkeypatch.setattr(main_module, "_probe_database", _healthy_database)
    monkeypatch.setattr(main_module, "_probe_redis", _hang)
    monkeypatch.setattr(main_module, "_probe_qdrant", _hang)
    monkeypatch.setattr(main_module, "_probe_minio", _hang)

    settings = SimpleNamespace(
        redis_url="redis://127.0.0.1:6399/0",
        qdrant_url="http://127.0.0.1:6399",
        minio_endpoint="127.0.0.1:6399",
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    try:
        checks = asyncio.run(_gather_ready(main_module))
    finally:
        release.set()

    assert checks["database"] == "ok"
    assert required_threads and required_threads[0] != caller_thread
    assert checks["redis"] == "error:TimeoutError"


async def _gather_ready(module):
    """Ejecuta el handler de readiness y devuelve el dict de checks interno."""
    import json

    from fastapi.responses import JSONResponse

    response = await module.health_ready()
    assert isinstance(response, JSONResponse)
    return json.loads(response.body)["checks"]


@pytest.mark.parametrize("path", ["/api/health", "/health/live", "/", "/health/ready"])
def test_ops_endpoints_stay_reachable(path):
    from fastapi.testclient import TestClient

    client = TestClient(main_module.app)
    assert client.get(path).status_code in (200, 503)


def test_health_reports_degraded_with_schema_migration_issues(monkeypatch):
    """SELECT 1 responde pero el esquema esta a medio migrar: /api/health
    debe decir degraded y exponer las incidencias (clase, nunca mensaje)."""
    monkeypatch.setattr(health_module, "_probe_database", lambda: "ok")
    issues = [{"statement": "ALTER TABLE positions ADD COLUMN fx", "error": "OperationalError"}]
    monkeypatch.setattr(health_module, "schema_migration_issues", lambda: issues)

    result = asyncio.run(health_module.health())

    assert result["status"] == "degraded"
    assert result["schema"] == issues


def test_health_ok_when_schema_clean(monkeypatch):
    monkeypatch.setattr(health_module, "_probe_database", lambda: "ok")
    monkeypatch.setattr(health_module, "schema_migration_issues", lambda: [])

    result = asyncio.run(health_module.health())

    assert result["status"] == "ok"
    assert result["schema"] == []
