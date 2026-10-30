"""Public health endpoint for the GerarAI data engine.

GET /api/health — sin firma (público): reporta estado de la BD, del
scheduler de workers y la versión del código. Pensado para orquestación
(load balancers, cron de monitoreo, deploy checks) que no tiene identidad
Research OS.

Como es público y lo consulta la orquestación, cada pieza cara va cacheada y
la sonda de BD corre en un hilo. Antes el handler era ``async def`` y hacía las
tres cosas en el event loop: un ``subprocess.run(git)`` por request (fork con
timeout de 2 s), un ``build_scheduler()`` completo (APScheduler con 18 jobs) y
un ``db.execute`` síncrono. Un barrido de sondas o un bucle contra este
endpoint serializaba el proceso entero.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal, schema_migration_issues
from app.services.data_source_health import get_data_source_registry

router = APIRouter(tags=["health"])

_REPO_ROOT = Path(__file__).resolve().parents[4]  # raíz del repo


@lru_cache(maxsize=1)
def _git_version() -> str:
    """Versión corta 'main-<sha>' del commit desplegado; 'main-unknown' si git no responde.

    Cacheado por proceso: el commit no cambia mientras el contenedor vive, y
    en la imagen de producción no hay git (el valor sale siempre de
    APP_VERSION, o 'main-unknown'), así que el fork se paga una sola vez.
    """
    pinned = (os.environ.get("APP_VERSION") or "").strip()
    if pinned:
        return pinned
    try:
        sha = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=2,
            )
            .stdout.strip()
        )
        return f"main-{sha}" if sha else "main-unknown"
    except Exception:  # noqa: BLE001 — el health nunca debe romperse por git
        return "main-unknown"


@lru_cache(maxsize=1)
def _scheduler_job_count() -> int:
    """Cuántos trabajos registraría el scheduler. Cacheado: solo depende del código.

    La construcción del APScheduler no se puede observar desde fuera, asi que
    se construye una vez y se cuenta. Antes se reconstruia en cada request.
    """
    from app.workers.scheduler import build_scheduler

    probe = build_scheduler(background=True)
    # Sin start() el probe no lanza hilos; no llamar shutdown() porque
    # APScheduler lanza SchedulerNotRunningError con un scheduler parado.
    return len(probe.get_jobs())


def _scheduler_status() -> dict:
    """Estado del scheduler de workers.

    La app arranca el scheduler dentro del lifespan (APScheduler en
    background) únicamente si WORKERS_ENABLED=true; no hay una instancia
    global observable desde este proceso, así que `running` refleja la
    config: si los workers están habilitados, el lifespan lo está
    ejecutando. `jobs` cuenta los trabajos registrados por build_scheduler.
    """
    settings = get_settings()
    if not settings.workers_enabled:
        # En produccion el scheduler corre en su propio servicio (cavaai-scheduler)
        # y esta API arranca con WORKERS_ENABLED=false: "enabled: false / running:
        # false" se leia como "no hay scheduler". Esta instancia no lo ejecuta y
        # no puede observarlo desde aqui: se declara tal cual (running: None =
        # desconocido, no "parado").
        return {
            "enabled": False,
            "running": None,
            "jobs": 0,
            "last_run_at": None,
            "external": True,
            "note": (
                "El scheduler corre en un servicio aparte; esta API no lo "
                "observa, no se puede afirmar que este parado ni activo."
            ),
        }
    try:
        return {
            "enabled": True,
            "running": True,
            "jobs": _scheduler_job_count(),
            "last_run_at": None,
        }
    except Exception as exc:  # noqa: BLE001 — reportar y seguir
        return {
            "enabled": True,
            "running": False,
            "jobs": 0,
            "last_run_at": None,
            # Solo el tipo de excepcion: este endpoint es publico y el texto
            # de un error de import/config puede traer rutas del host.
            "error": type(exc).__name__,
        }


def _probe_database() -> str:
    """SELECT 1 fuera del event loop; devuelve 'ok' o 'error:<Clase>'."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — surface dependency status
        return f"error:{type(exc).__name__}"


@router.get("/health")
async def health() -> dict:
    """Readiness: BD (SELECT 1), scheduler y versión."""
    database = await asyncio.to_thread(_probe_database)
    # El conteo de jobs y la versión ya vienen cacheados por proceso; aun
    # asi se resuelven en hilo para no hacer trabajo síncrono en el loop.
    scheduler, version = await asyncio.gather(
        asyncio.to_thread(_scheduler_status),
        asyncio.to_thread(_git_version),
    )
    # Esquema a medio migrar = degradado aunque SELECT 1 responda: la sonda
    # de BD no ve las columnas que faltan. Solo la CLASE del error se expone
    # (nunca texto de excepción, puede llevar SQL y rutas).
    schema_issues = schema_migration_issues()
    return {
        "status": "degraded" if database != "ok" or schema_issues else "ok",
        "database": database,
        "scheduler": scheduler,
        "version": version,
        "schema": [{"error": issue.get("error", "MigrationError")} for issue in schema_issues],
    }


@router.get("/health/data-sources")
@router.get("/data-sources")
def data_sources_health() -> dict:
    """Estado, latencia y circuit breakers de las fuentes de datos externas."""
    registry = get_data_source_registry()
    return registry.summary()
