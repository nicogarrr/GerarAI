"""Migracion 0101 (web push): crea las dos tablas, es idempotente y revierte."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _load():
    path = Path(__file__).parents[1] / "alembic/versions/0101_web_push.py"
    spec = importlib.util.spec_from_file_location("web_push_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn_module(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tenants (id INTEGER PRIMARY KEY)"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        yield conn, module


def test_upgrade_idempotent_and_downgrade(conn_module):
    conn, module = conn_module
    module.upgrade()
    names = set(inspect(conn).get_table_names())
    assert {"push_subscriptions", "push_preferences"} <= names
    assert any(c["column_names"] == ["tenant_id", "endpoint_hash"]
               for c in inspect(conn).get_unique_constraints("push_subscriptions"))
    assert any(c["column_names"] == ["tenant_id", "user_id", "event_type"]
               for c in inspect(conn).get_unique_constraints("push_preferences"))
    module.upgrade()  # adopta sin duplicar
    module.downgrade()
    assert not {"push_subscriptions", "push_preferences"} & set(inspect(conn).get_table_names())
    module.downgrade()  # idempotente


def test_revision_chain():
    module = _load()
    assert module.down_revision == "0100_ibkr_raw_row_snapshot_keys"
    assert len(module.revision) <= 32
