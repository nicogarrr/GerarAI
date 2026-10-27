import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_upgrade_adoption_and_rollback_preserve_connection_table(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0089_ibkr_connections.py"
    spec = importlib.util.spec_from_file_location("ibkr_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        columns = {c["name"]: c for c in inspect(conn).get_columns("ibkr_connections")}
        assert columns["tenant_id"]["nullable"] is False
        assert "token_ciphertext" in columns and "token" not in columns
        assert any(c["column_names"] == ["tenant_id"] for c in inspect(conn).get_unique_constraints("ibkr_connections"))
        module.upgrade()
        module.downgrade()
        assert inspect(conn).has_table("ibkr_connections")
        conn.exec_driver_sql("ALTER TABLE ibkr_connections ADD COLUMN unexpected INTEGER")
        with pytest.raises(RuntimeError, match="schema mismatch"):
            module.upgrade()
