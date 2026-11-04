"""Migration upgrade is additive, repeatable, and leaves tenant data untouched."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text


def test_upgrade_and_downgrade_touch_only_new_public_tables():
    path = Path(__file__).parents[1] / 'alembic/versions/0128_public_market_data.py'
    spec = importlib.util.spec_from_file_location('public_migration_actual', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE companies (id INTEGER PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE financial_facts (id INTEGER PRIMARY KEY, tenant_id INTEGER, value TEXT)'))
        conn.execute(text("INSERT INTO financial_facts VALUES (1, 2, 'private unchanged')"))
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()
        mod.upgrade()
        assert conn.execute(text('SELECT * FROM financial_facts')).all() == [(1, 2, 'private unchanged')]
        tables = set(inspect(conn).get_table_names())
        assert tables == {'companies', 'financial_facts', 'public_source_documents',
                          'public_financial_facts', 'public_financial_statements', 'public_analyst_targets'}
        for table in sorted(tables - {'companies', 'financial_facts'}):
            assert conn.scalar(select(func.count()).select_from(Table(table, MetaData(), autoload_with=conn))) == 0
        mod.downgrade()
        assert set(inspect(conn).get_table_names()) == {'companies', 'financial_facts'}
        assert conn.execute(text('SELECT * FROM financial_facts')).all() == [(1, 2, 'private unchanged')]
    engine.dispose()


def test_public_revision_extends_declared_inputs_and_is_the_only_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    root = Path(__file__).parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'alembic'))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ['0128_public_market_data']
    assert scripts.get_revision('0128_public_market_data').down_revision == '0127_declared_input_values'
