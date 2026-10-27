"""Additive migration keeps legacy raw values untouched and rejects drift."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_quote_unit_upgrade_downgrade_and_drift():
    path = Path(__file__).parents[1] / "alembic/versions/0087_market_price_quote_unit.py"
    spec = importlib.util.spec_from_file_location("quote_unit_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE market_prices (id INTEGER PRIMARY KEY, close NUMERIC)")
        connection.exec_driver_sql("INSERT INTO market_prices VALUES (1,4255)")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.exec_driver_sql("SELECT close,quote_currency FROM market_prices").one() == (4255, None)
        migration.downgrade()
        assert connection.exec_driver_sql("SELECT close FROM market_prices").scalar() == 4255
        migration.upgrade()
        migration.upgrade()  # adopt compatible create_all column
        migration.downgrade()
        assert "quote_currency" in {c["name"] for c in sa.inspect(connection).get_columns("market_prices")}
        connection.exec_driver_sql("ALTER TABLE market_prices DROP COLUMN quote_currency")
        connection.exec_driver_sql("ALTER TABLE market_prices ADD COLUMN quote_currency INTEGER")
        with pytest.raises(RuntimeError, match="schema mismatch"):
            migration.upgrade()
