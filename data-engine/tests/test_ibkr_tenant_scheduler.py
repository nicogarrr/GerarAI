from types import SimpleNamespace
from unittest.mock import MagicMock

from app.workers import dramatiq_app as workers


def test_scheduler_only_dispatches_enabled_connections_to_active_owner(monkeypatch):
    admin = MagicMock()
    admin.__enter__.return_value = admin
    admin.scalars.return_value.all.return_value = [11, 22]
    import app.core.database as database
    monkeypatch.setattr(database, "SessionLocal", lambda: admin)
    monkeypatch.setattr(workers, "tenant_contexts", lambda: [(11, "user-11"), (33, "user-33")])
    calls = []
    monkeypatch.setattr(workers.sync_one_tenant_ibkr, "send", lambda *args: calls.append(args))
    assert workers.sync_tenant_ibkr_connections.fn() == {"scheduled": 1}
    assert calls == [(11, "user-11")]


def test_legacy_sync_skips_even_disconnected_migrated_owner(monkeypatch):
    import app.core.database as database
    import app.services.connectors.ibkr as client
    admin = MagicMock()
    admin.__enter__.return_value = admin
    admin.scalar.return_value = 99
    monkeypatch.setattr(database, "SessionLocal", lambda: admin)
    monkeypatch.setattr(client, "IBKRFlexClient", lambda: SimpleNamespace())
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(ibkr_flex_tenant_id=11))
    assert workers.sync_ibkr_flex.fn()["reason"] == "tenant_connector"


def test_dedicated_dispatch_uses_its_own_queue(monkeypatch):
    admin = MagicMock()
    admin.__enter__.return_value = admin
    admin.scalars.return_value.all.return_value = [11]
    import app.core.database as database
    monkeypatch.setattr(database, "SessionLocal", lambda: admin)
    monkeypatch.setattr(workers, "tenant_contexts", lambda: [(11, "user-11")])
    monkeypatch.setattr(workers, "get_settings", lambda: SimpleNamespace(ibkr_dedicated_sync_enabled=True))
    calls = []
    monkeypatch.setattr(workers.sync_one_tenant_ibkr_dedicated, "send", lambda *args: calls.append(args))
    monkeypatch.setattr(workers.sync_one_tenant_ibkr, "send", lambda *args: (_ for _ in ()).throw(AssertionError("default queue")))
    assert workers.sync_tenant_ibkr_connections_dedicated.fn() == {"scheduled": 1}
    assert calls == [(11, "user-11")]
    assert workers.sync_tenant_ibkr_connections_dedicated.queue_name == "ibkr-sync"
    assert workers.sync_one_tenant_ibkr_dedicated.queue_name == "ibkr-sync"
    assert workers.evaluate_manual_dca.queue_name == "dca-manual"


def test_dedicated_consumer_preserves_the_existing_validated_import(monkeypatch):
    monkeypatch.setattr(workers.sync_one_tenant_ibkr, "fn", lambda tenant, user: {"tenant": tenant, "user": user})
    assert workers.sync_one_tenant_ibkr_dedicated.fn(22, "u22") == {"tenant": 22, "user": "u22"}


def test_schedule_is_opt_in_and_post_close_tracks_new_york_dst(monkeypatch):
    from datetime import UTC, datetime

    from app.workers import scheduler as sched

    settings = sched.get_settings()
    monkeypatch.setattr(settings, "ibkr_dedicated_sync_enabled", False)
    scheduler = sched.build_scheduler(background=True)
    assert scheduler.get_job("tenant_ibkr_post_close") is None
    # Los crons encolan via coalesced_send (dedup "una copia en vuelo");
    # el partial debe apuntar al actor IBKR que toca.
    legacy = scheduler.get_job("tenant_ibkr_flex_sync").func
    assert legacy.func is sched.coalesced_send
    assert legacy.args == (workers.sync_tenant_ibkr_connections,)
    monkeypatch.setattr(settings, "ibkr_dedicated_sync_enabled", True)
    scheduler = sched.build_scheduler(background=True)
    morning = scheduler.get_job("tenant_ibkr_flex_sync")
    evening = scheduler.get_job("tenant_ibkr_post_close")
    assert morning.func.func is sched.coalesced_send
    assert morning.func.args == (workers.sync_tenant_ibkr_connections_dedicated,)
    assert evening.func.func is sched.coalesced_send
    assert evening.func.args == (workers.sync_tenant_ibkr_connections_dedicated,)
    for start, expected in [(datetime(2026, 7, 15, tzinfo=UTC), 22), (datetime(2026, 12, 15, tzinfo=UTC), 23)]:
        fire = evening.trigger.get_next_fire_time(None, start)
        assert fire.hour == 18
        assert fire.astimezone(UTC).hour == expected
    assert morning.trigger.get_next_fire_time(None, datetime(2026, 7, 15, tzinfo=UTC)).hour == 6
