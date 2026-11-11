"""Migration preserves legacy defaults and never drops ORM-owned choices."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.models.entities import Base


def migration():
    path = Path(__file__).parents[1] / 'alembic/versions/0133_watch_auto_analysis.py'
    spec = importlib.util.spec_from_file_location('watch_auto_analysis', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_legacy_upgrade_default_and_owned_downgrade():
    mod = migration()
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE watch_items (id INTEGER PRIMARY KEY, symbol TEXT)'))
        conn.execute(text('CREATE TABLE migration_added_columns (revision TEXT, table_name TEXT, column_name TEXT)'))
        conn.execute(text("INSERT INTO watch_items (id,symbol) VALUES (1,'GFL')"))
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()
        assert conn.execute(text('SELECT auto_analysis_enabled FROM watch_items')).scalar() == 1
        conn.execute(text('UPDATE watch_items SET auto_analysis_enabled=0'))
        mod.upgrade()
        assert conn.execute(text('SELECT auto_analysis_enabled FROM watch_items')).scalar() == 0
        mod.downgrade()
        assert 'auto_analysis_enabled' not in {c['name'] for c in inspect(conn).get_columns('watch_items')}
        mod.downgrade()
        mod.upgrade()
        assert conn.execute(text('SELECT auto_analysis_enabled FROM watch_items')).scalar() == 1
    engine.dispose()


def test_orm_adoption_preserves_column_on_downgrade():
    mod = migration()
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        mod.op = Operations(MigrationContext.configure(conn))
        mod.upgrade()
        mod.downgrade()
        assert 'auto_analysis_enabled' in {c['name'] for c in inspect(conn).get_columns('watch_items')}
    engine.dispose()


def test_offline_sql_includes_default_and_ownership():
    from io import StringIO

    mod = migration()
    output = StringIO()
    mod.op = Operations(MigrationContext.configure(
        dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output},
    ))
    mod.upgrade()
    sql = output.getvalue()
    assert 'ADD COLUMN auto_analysis_enabled BOOLEAN DEFAULT true NOT NULL' in sql
    assert 'INSERT INTO migration_added_columns' in sql
    mod.downgrade()
    assert 'DROP COLUMN auto_analysis_enabled' in output.getvalue()
    assert 'DELETE FROM migration_added_columns' in output.getvalue()


def test_downgrade_without_log_preserves_existing_column():
    mod = migration()
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE watch_items (id INTEGER PRIMARY KEY, auto_analysis_enabled BOOLEAN NOT NULL DEFAULT true)'))
        mod.op = Operations(MigrationContext.configure(conn))
        mod.downgrade()
        assert 'auto_analysis_enabled' in {c['name'] for c in inspect(conn).get_columns('watch_items')}
    engine.dispose()
