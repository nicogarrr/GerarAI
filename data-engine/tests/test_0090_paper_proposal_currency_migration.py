import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_upgrade_preserves_legacy_unknown_and_downgrade_preserves_trades(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0090_paper_proposal_currency.py"
    spec = importlib.util.spec_from_file_location("paper_currency_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, currency VARCHAR(8), status VARCHAR(12))")
        conn.exec_driver_sql("INSERT INTO paper_trades VALUES (1, 'USD', 'open'), (2, NULL, 'pending')")
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()
        assert list(conn.exec_driver_sql("SELECT id,currency,status,proposal_currency,proposal_currency_known FROM paper_trades ORDER BY id")) == [(1, "USD", "open", None, 0), (2, None, "pending", None, 0)]
        conn.exec_driver_sql("INSERT INTO paper_trades(id,currency,status,proposal_currency,proposal_currency_known) VALUES (3,'USD','open',NULL,1)")
        module.downgrade()
        assert {c["name"] for c in inspect(conn).get_columns("paper_trades")} == {"id", "currency", "status"}
        assert list(conn.exec_driver_sql("SELECT * FROM paper_trades ORDER BY id")) == [(1,"USD","open"),(2,None,"pending"),(3,"USD","open")]
        # Re-upgrade cannot infer identities lost by a deliberate rollback.
        module.upgrade()
        assert list(conn.exec_driver_sql("SELECT proposal_currency,proposal_currency_known FROM paper_trades")) == [(None,0)] * 3
