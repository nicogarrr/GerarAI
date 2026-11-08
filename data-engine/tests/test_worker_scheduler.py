"""Scheduler de colas (APScheduler): jitter anti-manada, disparo al arrancar y fan-out.

El scheduler es la puerta de todas las colas periodicas; estaba al 0% de
cobertura. Estos tests fijan la politica anti-rafagas (jitter por defecto y
respeto del explicito), el adelanto del primer disparo de los intervalos
cortos y la forma de los fan-out por tenant.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from apscheduler.schedulers.background import BackgroundScheduler

from app.workers import scheduler as sched


def _noop() -> None:
    pass


def test_interval_seconds_suma_componentes() -> None:
    assert sched._interval_seconds({}) == 0
    assert sched._interval_seconds(
        {"weeks": 1, "days": 1, "hours": 1, "minutes": 1, "seconds": 1}
    ) == 604800 + 86400 + 3600 + 60 + 1


def test_startup_fire_time_none_para_intervalos_nulos_o_largos() -> None:
    assert sched._startup_fire_time({}) is None
    assert sched._startup_fire_time({"seconds": 0}) is None
    # Por encima del tope no hay adelanto: son jobs pesados o limitados por la fuente.
    assert sched._startup_fire_time({"hours": 2}) is None
    assert sched._startup_fire_time({"seconds": sched.STARTUP_FIRE_MAX_INTERVAL_SECONDS + 1}) is None


def test_startup_fire_time_dentro_del_propio_intervalo() -> None:
    now = datetime.now(UTC)
    fire = sched._startup_fire_time({"minutes": 15}, now=now)
    assert fire is not None
    delta = (fire - now).total_seconds()
    # low = min(30, high/2) con high = min(300, 900) -> [30, 300].
    assert 30 <= delta <= 300


def test_startup_fire_time_recorta_el_jitter_al_intervalo() -> None:
    now = datetime.now(UTC)
    fire = sched._startup_fire_time({"seconds": 10}, now=now)
    assert fire is not None
    delta = (fire - now).total_seconds()
    # high se recorta a 10 y low a 5: nunca supera el intervalo del job.
    assert 5 <= delta <= 10


def test_default_jitter_intervalo_acotado() -> None:
    assert sched._default_jitter("interval", {"hours": 1}) == 600  # tope superior
    assert sched._default_jitter("interval", {"minutes": 1}) == 10  # intervalo // 6
    assert sched._default_jitter("interval", {"seconds": 3}) == 1  # suelo inferior
    assert sched._default_jitter("interval", {}) == 300  # sin intervalo interpretable
    assert sched._default_jitter("cron", {"hour": 4}) == 300


def test_register_aplica_jitter_por_defecto_y_disparo_al_arrancar() -> None:
    s = BackgroundScheduler(timezone="UTC")
    sched._register(s, _noop, "interval", job_id="short", minutes=15)
    sched._register(s, _noop, "interval", job_id="long", hours=6)
    sched._register(s, _noop, "cron", job_id="cron", hour=4)
    jobs = {j.id: j for j in s.get_jobs()}
    assert jobs["short"].trigger.jitter == 150  # 900 // 6
    assert getattr(jobs["short"], "next_run_time", None) is not None
    assert jobs["long"].trigger.jitter == 600
    # Intervalos largos: sin adelanto al arrancar.
    assert getattr(jobs["long"], "next_run_time", None) is None
    assert jobs["cron"].trigger.jitter == 300
    # JOB_DEFAULTS anti-solape.
    for job in jobs.values():
        assert job.coalesce is True
        assert job.max_instances == 1
        assert job.misfire_grace_time == 900


def test_register_conserva_jitter_explicito() -> None:
    s = BackgroundScheduler(timezone="UTC")
    sched._register(s, _noop, "interval", job_id="expl", minutes=5, jitter=42)
    job = [j for j in s.get_jobs() if j.id == "expl"][0]
    assert job.trigger.jitter == 42


def test_build_scheduler_registra_la_parilla_completa() -> None:
    s = sched.build_scheduler(background=True)
    jobs = {j.id: j for j in s.get_jobs()}
    # Parilla medida: 71 jobs (42 cron + 29 interval). Se cota por debajo para
    # no romper si se anade un job, pero cualquier borrado se detecta.
    assert len(jobs) >= 70
    assert {"thesis_dispatch_recovery", "market_refresh", "market_refresh_universe"} <= set(jobs)
    # Ningun job sin jitter: la politica anti-manada cubre toda la parilla.
    assert all(getattr(j.trigger, "jitter", None) is not None for j in jobs.values())


def test_build_scheduler_adelanta_solo_intervalos_cortos() -> None:
    s = sched.build_scheduler(background=True)
    for job in s.get_jobs():
        trigger = job.trigger
        if type(trigger).__name__ != "IntervalTrigger":
            continue
        nrt = getattr(job, "next_run_time", None)
        if trigger.interval.total_seconds() <= sched.STARTUP_FIRE_MAX_INTERVAL_SECONDS:
            assert nrt is not None, job.id
        else:
            assert nrt is None, job.id


def test_enqueue_once_sin_tenants(monkeypatch) -> None:
    monkeypatch.setattr(sched, "tenant_contexts", lambda: iter([]))
    actor = SimpleNamespace(actor_name="fake_actor")
    assert sched.enqueue_once(actor) == {"actor": "fake_actor", "queued": []}


def test_enqueue_once_un_solo_contexto_aunque_haya_varios(monkeypatch) -> None:
    calls = []

    def fake_send(actor, tenant_id, user_id, **kwargs):
        calls.append((tenant_id, user_id, kwargs))
        return SimpleNamespace(message_id="m1")

    monkeypatch.setattr(sched, "tenant_contexts", lambda: [(1, 11), (2, 22)])
    monkeypatch.setattr(sched, "coalesced_send", fake_send)
    actor = SimpleNamespace(actor_name="fake_actor")
    out = sched.enqueue_once(actor, scope="tracked")
    # Datos globales: un solo contexto aunque existan N tenants.
    assert calls == [(1, 11, {"scope": "tracked"})]
    assert out == {"actor": "fake_actor", "queued": ["m1"]}


def test_enqueue_once_suprimido_por_coalescencia(monkeypatch) -> None:
    monkeypatch.setattr(sched, "tenant_contexts", lambda: [(1, 11)])
    monkeypatch.setattr(sched, "coalesced_send", lambda *a, **k: None)
    actor = SimpleNamespace(actor_name="fake_actor")
    assert sched.enqueue_once(actor) == {"actor": "fake_actor", "queued": [], "suppressed": True}


def test_enqueue_for_all_tenants_marca_suprimidos(monkeypatch) -> None:
    def fake_send(actor, tenant_id, user_id, **kwargs):
        return None if tenant_id == 2 else SimpleNamespace(message_id=f"m{tenant_id}")

    monkeypatch.setattr(sched, "tenant_contexts", lambda: [(1, 11), (2, 22)])
    monkeypatch.setattr(sched, "coalesced_send", fake_send)
    actor = SimpleNamespace(actor_name="fake_actor")
    out = sched.enqueue_for_all_tenants(actor)
    assert out["actor"] == "fake_actor"
    assert out["queued"] == [
        {"tenant_id": 1, "user_id": 11, "message_id": "m1"},
        {"tenant_id": 2, "user_id": 22, "suppressed": True},
    ]


def test_enqueue_insider_scan_propaga_alcance(monkeypatch) -> None:
    monkeypatch.setattr(sched, "tenant_contexts", lambda: [(7, 70)])
    monkeypatch.setattr(sched, "coalesced_send", lambda *a: SimpleNamespace(message_id="mx"))
    out = sched.enqueue_insider_scan(lookback=3, max_new_fetches=5)
    assert out["actor"] == sched.scan_insider_watchlist.actor_name
    assert out["lookback"] == 3
    assert out["max_new_fetches"] == 5
    assert out["queued"] == [{"tenant_id": 7, "user_id": 70, "message_id": "mx"}]


def test_enqueue_official_closes_once_usa_un_contexto(monkeypatch) -> None:
    monkeypatch.setattr(sched, "tenant_contexts", lambda: [(9, 90), (10, 100)])
    monkeypatch.setattr(sched, "coalesced_send", lambda *a, **k: SimpleNamespace(message_id="c1"))
    out = sched.enqueue_official_closes_once()
    assert out["actor"] == sched.sync_official_closes.actor_name
    assert out["queued"] == ["c1"]
