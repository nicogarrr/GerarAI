import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _load():
    path = Path(__file__).parents[1] / "alembic/versions/0093_paper_trade_costs.py"
    spec = importlib.util.spec_from_file_location("paper_costs_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_nullable_and_idempotent_downgrade_preserves_trades(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, status VARCHAR(12))")
        conn.exec_driver_sql("INSERT INTO paper_trades VALUES (1, 'closed'), (2, 'open')")
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()  # idempotente
        rows = list(conn.exec_driver_sql(
            "SELECT id, status, entry_fee, exit_fee, cost_assumption_version FROM paper_trades ORDER BY id"))
        assert rows == [(1, "closed", None, None, None), (2, "open", None, None, None)]
        conn.exec_driver_sql(
            "INSERT INTO paper_trades(id,status,entry_fee,exit_fee,cost_assumption_version) "
            "VALUES (3,'closed',1.1,1.085,'supuesto-v1|fija=1.00|spread_bps=5')")
        module.downgrade()
        assert {c["name"] for c in inspect(conn).get_columns("paper_trades")} == {"id", "status"}
        assert list(conn.exec_driver_sql("SELECT * FROM paper_trades ORDER BY id")) == [
            (1, "closed"), (2, "open"), (3, "closed")]
