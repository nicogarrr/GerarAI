"""Guardia del invariante de coalescencia: ventana < cadencia del scheduler.

El claim de _coalesce_on_success vive `window` segundos DESDE el inicio de
la corrida. Si la ventana no es estrictamente menor que la cadencia, el
tick siguiente puede consumirse con el claim anterior aun fresco (el jitter
de _register llega a cadencia/6 y hay arranques adelantados) y skippearse
sin trabajar: la cadencia efectiva se dobla de forma intermitente.
Hallazgo 9-nov-2026: house_ptr tenia ventana 6 h = cadencia 6 h. El
docstring de _coalesce_on_success declara el invariante («todas las
ventanas son menores que la cadencia de su scheduler»); esta guardia lo
fija para todos los jobs registrados, como test_scheduler_jitter_guard
fija el jitter.
"""
from __future__ import annotations

from unittest.mock import patch

from dramatiq import Actor

import app.workers.scheduler as sched
from app.workers.dramatiq_app import _COALESCE_POLICIES

# Helpers de fan-out que NO reciben el actor como argumento del partial:
# mapeo explicito al unico actor coalescido que encolan.
_HELPER_ACTORS = {"enqueue_insider_scan": "scan_insider_watchlist"}


def _registered_jobs() -> list[tuple[str, str, dict, object]]:
    jobs: list[tuple[str, str, dict, object]] = []

    class Fake:
        def add_job(self, func, trigger, id=None, **kw):
            jobs.append((id, trigger, kw, func))

    with patch.object(sched, "BlockingScheduler", return_value=Fake()), patch.object(
        sched, "tenant_contexts", return_value=[]
    ), patch("app.workers.dramatiq_app._redis_client", return_value=None):
        sched.build_scheduler()
    return jobs


def _resolve(func) -> tuple[str, dict] | None:
    """(nombre de actor, kwargs de envio) o None si el job no dispara un actor."""
    if isinstance(func, Actor):
        return func.actor_name, {}
    keywords = dict(getattr(func, "keywords", {}) or {})
    for arg in getattr(func, "args", ()):
        if isinstance(arg, Actor):
            return arg.actor_name, keywords
    inner_name = getattr(getattr(func, "func", None), "__name__", "")
    if inner_name in _HELPER_ACTORS:
        return _HELPER_ACTORS[inner_name], {}
    return None


def _cadence_seconds(trigger: str, kw: dict) -> int | None:
    """Cota inferior de la cadencia en segundos, o None si no es derivable."""
    if trigger == "interval":
        return sched._interval_seconds(kw)
    if trigger == "cron":
        if "day_of_week" in kw:
            return 7 * 86400
        if "day" in kw or "month" in kw:
            return None  # cadencia mensual o irregular: no derivable en simple
        if "hour" in kw:
            return 86400
        if "minute" in kw:
            return 3600
    return None


def test_coalesce_window_siempre_menor_que_la_cadencia():
    jobs = _registered_jobs()
    assert jobs, "build_scheduler no registro ningun job (el fake no capturo)"
    comprobados: list[str] = []
    offenders: list[str] = []
    for job_id, trigger, kw, func in jobs:
        resolved = _resolve(func)
        if resolved is None:
            continue
        actor_name, send_kwargs = resolved
        policy = _COALESCE_POLICIES.get(actor_name)
        if policy is None:
            continue
        window = policy["window"]
        window_s = int(window(**send_kwargs) if callable(window) else window)
        cadence = _cadence_seconds(trigger, kw)
        if cadence is None:
            continue
        comprobados.append(job_id)
        if window_s >= cadence:
            offenders.append(
                f"{job_id}: ventana coalesce {window_s}s >= cadencia {cadence}s "
                f"(actor {actor_name})"
            )
    assert comprobados, "ningun job comprobado: la resolucion de actores se rompio"
    assert not offenders, (
        "Ventanas de coalescencia que pueden seguir frescas en el siguiente tick:\n"
        + "\n".join(offenders)
    )


def test_house_ptr_ventana_fijada_bajo_cadencia_de_6h():
    # Regresion del caso medido: cadencia 6 h (21600 s) y ventana
    # estrictamente menor (el resto de ingests de 6 h usan 19800).
    policy = _COALESCE_POLICIES["ingest_house_ptr"]
    assert int(policy["window"]) < 6 * 60 * 60
