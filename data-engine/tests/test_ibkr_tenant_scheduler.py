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
