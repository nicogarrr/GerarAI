"""Helpers de fan-out del scheduler: dedup por copia en vuelo, un solo contexto
global, jitter por defecto, import perezoso de scripts/ y apagado de main()."""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.workers import scheduler


def _fake_tenants(monkeypatch, contexts):
    monkeypatch.setattr(scheduler, "tenant_contexts", lambda: contexts)


def test_enqueue_for_all_tenants_encola_y_marca_suprimidos(monkeypatch):
    _fake_tenants(monkeypatch, [(1, "u1"), (2, "u2")])
    enviados = []

    def fake_send(actor, tenant_id, user_id, **kwargs):
        enviados.append((actor.actor_name, tenant_id, user_id, kwargs))
        if tenant_id == 2:
            return None  # ya hay una copia en vuelo: tick suprimido
        return SimpleNamespace(message_id="mid-1")

    monkeypatch.setattr(scheduler, "coalesced_send", fake_send)
    actor = scheduler.refresh_earnings_calendar
    out = scheduler.enqueue_for_all_tenants(actor, scope="tracked")
    assert out == {
        "actor": actor.actor_name,
        "queued": [
            {"tenant_id": 1, "user_id": "u1", "message_id": "mid-1"},
            {"tenant_id": 2, "user_id": "u2", "suppressed": True},
        ],
    }
    assert enviados[0][3] == {"scope": "tracked"}


def test_enqueue_insider_scan_pasa_alcance_posicional(monkeypatch):
    _fake_tenants(monkeypatch, [(7, "u7")])
    enviados = []
    monkeypatch.setattr(
        scheduler,
        "coalesced_send",
        lambda actor, *args: enviados.append(args) or SimpleNamespace(message_id="m-9"),
    )
    out = scheduler.enqueue_insider_scan(lookback=3, max_new_fetches=40)
    assert enviados == [(7, "u7", 3, 40)]
    assert out["actor"] == scheduler.scan_insider_watchlist.actor_name
    assert out["lookback"] == 3 and out["max_new_fetches"] == 40
    assert out["queued"] == [{"tenant_id": 7, "user_id": "u7", "message_id": "m-9"}]


def test_enqueue_insider_scan_marca_suprimidos(monkeypatch):
    _fake_tenants(monkeypatch, [(1, "u1"), (2, "u2")])
    monkeypatch.setattr(
        scheduler,
        "coalesced_send",
        lambda actor, *args: None if args[0] == 2 else SimpleNamespace(message_id="m-1"),
    )
    out = scheduler.enqueue_insider_scan(lookback=1, max_new_fetches=10)
    assert out["queued"] == [
        {"tenant_id": 1, "user_id": "u1", "message_id": "m-1"},
        {"tenant_id": 2, "user_id": "u2", "suppressed": True},
    ]


def test_enqueue_once_sin_tenants_no_encola(monkeypatch):
    _fake_tenants(monkeypatch, [])
    actor = scheduler.sync_official_closes
    assert scheduler.enqueue_once(actor) == {"actor": actor.actor_name, "queued": []}


def test_enqueue_once_solo_el_primer_contexto(monkeypatch):
    _fake_tenants(monkeypatch, [(1, "u1"), (2, "u2")])
    enviados = []
    monkeypatch.setattr(
        scheduler,
        "coalesced_send",
        lambda actor, *args: enviados.append(args) or SimpleNamespace(message_id="m-1"),
    )
    actor = scheduler.sync_official_closes
    out = scheduler.enqueue_once(actor)
    assert enviados == [(1, "u1")]  # dato global: un solo mensaje, no uno por tenant
    assert out == {"actor": actor.actor_name, "queued": ["m-1"]}


def test_enqueue_once_suprimido_por_copia_en_vuelo(monkeypatch):
    _fake_tenants(monkeypatch, [(1, "u1")])
    monkeypatch.setattr(scheduler, "coalesced_send", lambda actor, *args: None)
    actor = scheduler.sync_official_closes
    assert scheduler.enqueue_once(actor) == {
        "actor": actor.actor_name,
        "queued": [],
        "suppressed": True,
    }


def test_enqueue_official_closes_once_delega_en_enqueue_once(monkeypatch):
    visto = {}
    monkeypatch.setattr(
        scheduler,
        "enqueue_once",
        lambda actor, **kwargs: visto.setdefault("actor", actor) or {"actor": actor.actor_name},
    )
    scheduler.enqueue_official_closes_once()
    assert visto["actor"] is scheduler.sync_official_closes


def test_default_jitter_acotado():
    # Intervalo invalido o cron: 300 s fijos; intervalo valido: <= 600 s.
    assert scheduler._default_jitter("interval", {}) == 300
    assert scheduler._default_jitter("cron", {}) == 300
    assert scheduler._default_jitter("interval", {"hours": 2}) == 600
    assert scheduler._default_jitter("interval", {"seconds": 30}) == 5


class _Capturador:
    """add_job falso: registra los kwargs sin APScheduler de por medio."""

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, id, **kwargs):
        self.jobs[id] = {"trigger": trigger, "kwargs": kwargs, "func": func}


def test_register_respeta_jitter_explicito_y_anticipa_intervalos():
    capt = _Capturador()
    scheduler._register(capt, lambda: None, "interval", job_id="j1", minutes=5, jitter=42)
    assert capt.jobs["j1"]["kwargs"]["jitter"] == 42  # un jitter explicito manda
    assert "next_run_time" in capt.jobs["j1"]["kwargs"]  # intervalo corto: tiro al arrancar

    scheduler._register(capt, lambda: None, "interval", job_id="j2", hours=3)
    assert capt.jobs["j2"]["kwargs"]["jitter"] == 600
    assert "next_run_time" not in capt.jobs["j2"]["kwargs"]  # > 1 h: sin adelanto

    scheduler._register(capt, lambda: None, "cron", job_id="j3", hour=4)
    assert capt.jobs["j3"]["kwargs"]["jitter"] == 300


def test_refresh_instrument_references_import_perezoso(monkeypatch):
    modulo = types.ModuleType("scripts.sync_instruments")
    modulo.refresh_weekly = lambda: {"refrescados": 7}
    monkeypatch.setitem(sys.modules, "scripts.sync_instruments", modulo)
    assert scheduler._refresh_instrument_references() == {"refrescados": 7}


def test_build_scheduler_con_ibkr_dedicado_y_retencion(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: SimpleNamespace(ibkr_dedicated_sync_enabled=True, retention_job_enabled=True),
    )
    sched = scheduler.build_scheduler(background=True)
    ids = {job.id for job in sched.get_jobs()}
    # Con la sync dedicada activa existe el tick post-cierre de NY...
    assert "tenant_ibkr_post_close" in ids
    # ...y con la retencion activa se registra el job de privacidad.
    assert "privacy_retention" in ids


def test_main_cierra_sin_esperar_tras_keyboard_interrupt(monkeypatch):
    falso = MagicMock()
    falso.start.side_effect = KeyboardInterrupt
    monkeypatch.setattr(scheduler, "build_scheduler", lambda background: falso)
    scheduler.main()
    falso.shutdown.assert_called_once_with(wait=False)
