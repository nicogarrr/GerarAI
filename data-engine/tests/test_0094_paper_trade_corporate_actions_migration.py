import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def _load():
    path = Path(__file__).parents[1] / "alembic/versions/0094_paper_trade_corporate_actions.py"
    spec = importlib.util.spec_from_file_location("paper_ca_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_idempotent_and_downgrade_preserves_trades(monkeypatch):
    module = _load()
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, status VARCHAR(12))")
        conn.exec_driver_sql("INSERT INTO paper_trades VALUES (1, 'closed'), (2, 'open')")
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()
        rows = list(conn.exec_driver_sql(
            "SELECT id, status, dividends_total, corporate_action_warning FROM paper_trades ORDER BY id"))
        assert rows == [(1, "closed", None, None), (2, "open", None, None)]
        conn.exec_driver_sql(
            "INSERT INTO paper_trades(id,status,dividends_total,corporate_action_warning) "
            "VALUES (3,'closed',1.5,'split_cerrado_sin_ajustar')")
        module.downgrade()
        assert {c["name"] for c in inspect(conn).get_columns("paper_trades")} == {"id", "status"}
        assert list(conn.exec_driver_sql("SELECT * FROM paper_trades ORDER BY id")) == [
            (1, "closed"), (2, "open"), (3, "closed")]


def test_revision_fits_alembic_version_column_and_keeps_chain():
    module = _load()
    context = MigrationContext.configure(dialect_name="postgresql")
    limit = context._version.c.version_num.type.length
    assert len(module.revision) <= limit
    assert module.revision == "0094_paper_trade_actions"
    assert module.down_revision == "0093_paper_trade_costs"
