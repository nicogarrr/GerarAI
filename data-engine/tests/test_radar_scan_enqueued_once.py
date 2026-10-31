"""El scan del radar son datos publicos globales: un solo encolado diario.

Antes se encolaba con ``enqueue_for_all_tenants``: con N tenants llegaban N
mensajes y N-1 corridas terminaban en ``skipped/lease_held`` por el lease.
Mismo patron que los cierres oficiales (``enqueue_official_closes_once``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.workers import dramatiq_app
from app.workers import scheduler as sched


def test_scheduler_registers_radar_scan_with_enqueue_once(monkeypatch):
    seen: dict[str, tuple[str, dict, Any]] = {}
    orig = sched._register

    def spy(scheduler, func, trigger, *, job_id, **kw):
        orig(scheduler, func, trigger, job_id=job_id, **kw)
        seen[job_id] = (trigger, dict(kw), func)

    monkeypatch.setattr(sched, "_register", spy)
    sched.build_scheduler(background=True)
    trigger, kwargs, func = seen["propicks_radar_scan_daily"]
    assert trigger == "cron"
    assert (kwargs["hour"], kwargs["minute"]) == (23, 0)
    assert func.func is sched.enqueue_once
    assert func.args == (dramatiq_app.propicks_radar_scan,)


def test_enqueue_once_sends_single_message_with_first_context(monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "tenant_contexts", lambda: [(1, "a"), (2, "b")])
    monkeypatch.setattr(
        dramatiq_app.propicks_radar_scan,
        "send",
        lambda *a: calls.append(a) or SimpleNamespace(message_id="m1"),
    )
    out = sched.enqueue_once(dramatiq_app.propicks_radar_scan)
    assert calls == [(1, "a")]
    assert out == {"actor": "propicks_radar_scan", "queued": ["m1"]}


def test_enqueue_once_without_tenants_sends_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(sched, "tenant_contexts", lambda: [])
    monkeypatch.setattr(
        dramatiq_app.propicks_radar_scan,
        "send",
        lambda *a: calls.append(a) or SimpleNamespace(message_id="m1"),
    )
    out = sched.enqueue_once(dramatiq_app.propicks_radar_scan)
    assert calls == []
    assert out == {"actor": "propicks_radar_scan", "queued": []}
