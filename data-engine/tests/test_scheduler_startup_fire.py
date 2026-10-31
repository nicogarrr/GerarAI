"""Los intervalos cortos disparan al arrancar (con jitter); los largos no."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.workers import scheduler as sched


class _Fake:
    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs["id"]] = (trigger, kwargs)


def test_short_interval_gets_a_first_fire_within_five_minutes():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    for args in ({"minutes": 15}, {"minutes": 1}, {"hours": 1}, {"minutes": 30, "jitter": 60}):
        first = sched._startup_fire_time(args, now)
        assert first is not None
        interval = sched._interval_seconds(args)
        assert now < first <= now + timedelta(seconds=min(300, interval))


def test_long_interval_does_not_fire_at_startup():
    assert sched._startup_fire_time({"hours": 2}) is None
    assert sched._startup_fire_time({"hours": 6}) is None
    assert sched._startup_fire_time({}) is None


def test_register_sets_next_run_time_only_for_short_intervals():
    fake = _Fake()
    sched._register(fake, lambda: None, "interval", job_id="short", minutes=15)
    sched._register(fake, lambda: None, "interval", job_id="long", hours=6)
    sched._register(fake, lambda: None, "cron", job_id="cron", hour=6, minute=40)
    assert "next_run_time" in fake.jobs["short"][1]
    assert "next_run_time" not in fake.jobs["long"][1]
    assert "next_run_time" not in fake.jobs["cron"][1]


def test_build_scheduler_registers_rss_refresh_with_startup_fire(monkeypatch):
    seen = {}
    orig = sched._register

    def spy(scheduler, func, trigger, *, job_id, **kw):
        orig(scheduler, func, trigger, job_id=job_id, **kw)
        seen[job_id] = (trigger, dict(kw))

    monkeypatch.setattr(sched, "_register", spy)
    sched.build_scheduler(background=True)
    assert "rss_refresh" in seen and seen["rss_refresh"][0] == "interval"


def test_one_minute_job_is_not_delayed_beyond_its_own_interval():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    for _ in range(200):
        first = sched._startup_fire_time({"minutes": 1}, now)
        assert first <= now + timedelta(seconds=60)


def test_real_apscheduler_first_fire_explicit_time_and_interval(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.start(paused=True)
    try:
        sched._register(scheduler, lambda: None, "interval", job_id="one_min", minutes=1)
        before = datetime.now(UTC)
        job = scheduler.get_job("one_min")
        assert job.next_run_time is not None
        assert job.next_run_time <= before + timedelta(seconds=61)
        # El siguiente disparo mantiene el intervalo de 1 min desde el primero,
        # mas el jitter anti-manada por defecto (intervalo/6 -> 10 s en 1 min).
        nxt = job.trigger.get_next_fire_time(job.next_run_time, job.next_run_time)
        assert timedelta(minutes=1) <= nxt - job.next_run_time <= timedelta(minutes=1, seconds=10)

        explicit = datetime.now(UTC) + timedelta(hours=3)
        sched._register(
            scheduler, lambda: None, "interval", job_id="explicit", minutes=15, next_run_time=explicit
        )
        assert scheduler.get_job("explicit").next_run_time == explicit
    finally:
        scheduler.shutdown(wait=False)


def test_real_apscheduler_runs_the_job_at_startup_and_again_per_interval():
    import time

    from apscheduler.schedulers.background import BackgroundScheduler

    calls = []
    scheduler = BackgroundScheduler(timezone="UTC")
    sched._register(scheduler, lambda: calls.append(time.monotonic()), "interval", job_id="fast", seconds=2)
    scheduler.start()
    try:
        time.sleep(5.5)
    finally:
        scheduler.shutdown(wait=False)
    assert len(calls) >= 2, calls
    assert calls[1] - calls[0] >= 1.5
