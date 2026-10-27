"""The isolation migration never changes legacy data or guesses its owner."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_upgrade_downgrade_preserves_all_rows(monkeypatch):
    path = Path(__file__).parents[1] / 'alembic/versions/0088_inferred_input_tenant_index.py'
    spec = importlib.util.spec_from_file_location('isolation_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE inferred_inputs (id INTEGER PRIMARY KEY, tenant_id INTEGER, company_id INTEGER, input_key TEXT, value TEXT, base TEXT, source_urls TEXT)'))
        conn.execute(text("INSERT INTO inferred_inputs VALUES (1,2,1,'wacc','0.15','original owner input','[]'), (2,5,1,'wacc','0.12','audit owner input','[]'), (3,NULL,1,'wacc','0.1','unknown owner input','[]')"))
        before = conn.execute(text('SELECT * FROM inferred_inputs ORDER BY id')).all()
        monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()  # create_all/adopted index is safe and idempotent
        assert module.INDEX in {i['name'] for i in inspect(conn).get_indexes('inferred_inputs')}
        assert conn.execute(text('SELECT * FROM inferred_inputs ORDER BY id')).all() == before
        module.downgrade()
        assert module.INDEX not in {i['name'] for i in inspect(conn).get_indexes('inferred_inputs')}
        assert conn.execute(text('SELECT * FROM inferred_inputs ORDER BY id')).all() == before
    engine.dispose()
