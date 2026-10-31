"""Guardia anti-manada: todo job periodico del scheduler lleva jitter.

Los jobs de igual cadencia sin jitter disparan en el mismo segundo (todos
los de 6 h a las :00, los de 1 h a las :00, los de 30 min a :00/:30): una
rafaga sincronizada que satura worker, Redis y proveedores justo en el
mismo instante. MEDIDO 2026-10-31: 44 de 65 jobs registrados no declaraban
jitter. ``_register`` aplica ahora un jitter por defecto (intervalo//6
acotado a [5, 600] en interval; 300 s en cron) y esta guardia fija que
ningun job registrado queda sin el, y que el jitter nunca alcanza la mitad
de la cadencia (un jitter >= intervalo/2 solaparia ticks vecinos).
"""
from __future__ import annotations

from unittest.mock import patch

import app.workers.scheduler as sched


def _registered_jobs() -> list[tuple[str, str, dict]]:
    jobs: list[tuple[str, str, dict]] = []

    class Fake:
        def add_job(self, func, trigger, id=None, **kw):
            jobs.append((id, trigger, kw))

    with patch.object(sched, "BlockingScheduler", return_value=Fake()), patch.object(
        sched, "tenant_contexts", return_value=[]
    ), patch("app.workers.dramatiq_app._redis_client", return_value=None):
        sched.build_scheduler()
    return jobs


def test_every_registered_job_has_jitter_within_half_its_cadence():
    jobs = _registered_jobs()
    assert jobs, "build_scheduler no registro ningun job (el fake no capturo)"
    offenders = []
    for job_id, trigger, kw in jobs:
        jitter = kw.get("jitter")
        if not isinstance(jitter, int) or jitter <= 0:
            offenders.append(f"{job_id} ({trigger}) sin jitter")
            continue
        if trigger == "interval":
            interval = sched._interval_seconds(kw)
            if interval > 0 and jitter > interval // 2:
                offenders.append(
                    f"{job_id} jitter={jitter}s > mitad de cadencia={interval}s"
                )
    assert not offenders, "Jobs sin jitter valido:\n" + "\n".join(offenders)
