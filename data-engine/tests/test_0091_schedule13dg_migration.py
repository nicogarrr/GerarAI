"""Migracion 0091 (schedule_13dg_filings): creacion, adopcion idempotente,
rollback y rechazo de esquemas ajenos."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _load():
    path = Path(__file__).parents[1] / "alembic/versions/0091_schedule_13dg_filings.py"
    spec = importlib.util.spec_from_file_location("schedule13dg_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adoption_and_rollback(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        columns = {c["name"]: c for c in inspect(conn).get_columns("schedule_13dg_filings")}
        assert columns["accession_number"]["nullable"] is False
        assert columns["aggregate_shares"]["nullable"] is True
        assert columns["percent_of_class"]["nullable"] is True
        assert columns["snapshot_date"]["nullable"] is True
        assert any(
            c["column_names"] == ["tenant_id", "accession_number"]
            for c in inspect(conn).get_unique_constraints("schedule_13dg_filings")
        )
        # Idempotente: re-correr upgrade adopta el esquema identico.
        module.upgrade()
        module.downgrade()
        assert not inspect(conn).has_table("schedule_13dg_filings")


def test_upgrade_rejects_foreign_schema(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        conn.exec_driver_sql("CREATE TABLE schedule_13dg_filings (id INTEGER PRIMARY KEY)")
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()
