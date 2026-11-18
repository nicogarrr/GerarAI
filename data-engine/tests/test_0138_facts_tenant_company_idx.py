"""0138 operations: real SQLite/PG round trips and invalid-index recovery."""
import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.schema import CreateSchema, DropSchema

PATH = Path(__file__).parents[1] / 'alembic/versions/0138_facts_tenant_company_idx.py'
spec = importlib.util.spec_from_file_location('migration_0138', PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def run(conn, action):
    context = MigrationContext.configure(conn)
    with context.begin_transaction():
        with Operations.context(context):
            action()


@pytest.fixture(params=['sqlite', 'postgres'])
def connection(request):
    url = os.environ.get('FACTS_INDEX_TEST_PG_URL') if request.param == 'postgres' else 'sqlite:///:memory:'
    if not url:
        pytest.skip('Set FACTS_INDEX_TEST_PG_URL to a disposable PostgreSQL database')
    engine = sa.create_engine(url)
    schema = 'facts_index_' + uuid4().hex
    conn = engine.connect()
    if request.param == 'postgres':
        conn.execute(CreateSchema(schema))
        # Generated UUID identifier quoted by the dialect, not user SQL.
        conn.exec_driver_sql('SET search_path TO ' + conn.dialect.identifier_preparer.quote_schema(schema))
        conn.commit()
    metadata = sa.MetaData()
    table = sa.Table('financial_facts', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('tenant_id', sa.Integer), sa.Column('company_id', sa.Integer))
    metadata.create_all(conn)
    conn.execute(table.insert(), [{'id': 1, 'tenant_id': 1, 'company_id': 10},
                                  {'id': 2, 'tenant_id': 2, 'company_id': 10}])
    conn.commit()
    try:
        yield conn, table
    finally:
        conn.rollback()
        if request.param == 'postgres':
            conn.execute(DropSchema(schema, cascade=True))
            conn.commit()
        conn.close()
        engine.dispose()


def test_upgrade_reentry_downgrade_preserves_rows_and_exact_columns(connection):
    conn, table = connection
    baseline = conn.execute(sa.select(table).order_by(table.c.id)).all()
    conn.commit()
    run(conn, migration.upgrade)
    indexes = {row['name']: row for row in sa.inspect(conn).get_indexes('financial_facts')}
    assert indexes[migration.INDEX]['column_names'] == ['tenant_id', 'company_id']
    assert not indexes[migration.INDEX]['unique']
    conn.commit()
    if conn.dialect.name == 'postgresql':
        oid = conn.execute(sa.text('SELECT CAST(:name AS regclass)::oid'), {'name': migration.INDEX}).scalar_one()
        conn.commit()
    run(conn, migration.upgrade)
    if conn.dialect.name == 'postgresql':
        assert conn.execute(sa.text('SELECT CAST(:name AS regclass)::oid'), {'name': migration.INDEX}).scalar_one() == oid
        conn.commit()
    assert conn.execute(sa.select(table).order_by(table.c.id)).all() == baseline
    conn.commit()
    run(conn, migration.downgrade)
    assert migration.INDEX not in {i['name'] for i in sa.inspect(conn).get_indexes('financial_facts')}
    conn.commit()
    run(conn, migration.downgrade)
    assert conn.execute(sa.select(table).order_by(table.c.id)).all() == baseline
    conn.commit()


def test_postgres_invalid_concurrent_index_recovers_without_data_change(connection):
    conn, table = connection
    if conn.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL invalid index state only')
    # Duplicate values make UNIQUE CONCURRENTLY fail after leaving an INVALID
    # index. The production index is nonunique; upgrade must replace the remnant.
    conn.execution_options(isolation_level='AUTOCOMMIT')
    with pytest.raises(sa.exc.IntegrityError):
        conn.exec_driver_sql('CREATE UNIQUE INDEX CONCURRENTLY ix_facts_tenant_company_count ON financial_facts(company_id)')
    conn.rollback()
    assert migration._invalid(conn)
    conn.rollback()
    run(conn, migration.upgrade)
    assert not migration._invalid(conn)
    assert conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 2
    conn.commit()
    run(conn, migration.downgrade)

def test_pg_invalid_branch_uses_concurrent_autocommit_and_exact_keys(monkeypatch):
    bind = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
    entered = []
    @contextmanager
    def block():
        entered.append('enter')
        yield
        entered.append('exit')
    operations = SimpleNamespace(get_bind=lambda: bind,
        get_context=lambda: SimpleNamespace(autocommit_block=block),
        drop_index=Mock(), create_index=Mock())
    monkeypatch.setattr(migration, 'op', operations)
    monkeypatch.setattr(migration, '_invalid', lambda bind: True)
    monkeypatch.setattr(migration, '_schema', lambda bind: 'target_schema')
    migration.upgrade()
    operations.drop_index.assert_called_once_with(migration.INDEX, table_name='financial_facts', schema='target_schema',
        postgresql_concurrently=True, if_exists=True)
    operations.create_index.assert_called_once_with(migration.INDEX, 'financial_facts',
        ['tenant_id', 'company_id'], schema='target_schema', postgresql_concurrently=True, if_not_exists=True)
    assert entered == ['enter', 'exit']


def test_orm_index_matches_migration():
    from app.models import FinancialFact

    index = next(i for i in FinancialFact.__table__.indexes if i.name == migration.INDEX)
    assert [column.name for column in index.columns] == ['tenant_id', 'company_id']
    assert not index.unique


@pytest.mark.parametrize('invalid', [False, True])
def test_pg_search_path_collision_preserves_foreign_index(connection, invalid):
    conn, table = connection
    if conn.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL namespaces only')
    target = migration._schema(conn)
    conn.commit()
    # Mixed case and spaces also exercise dialect identifier quoting.
    foreign = 'Foreign Index ' + uuid4().hex
    quote = conn.dialect.identifier_preparer.quote_schema
    conn.execute(CreateSchema(foreign))
    try:
        conn.exec_driver_sql('CREATE TABLE ' + quote(foreign) + '.other_table(id int)')
        conn.exec_driver_sql('CREATE INDEX ix_facts_tenant_company_count ON ' + quote(foreign) + '.other_table(id)')
        conn.exec_driver_sql('SET search_path TO ' + quote(foreign) + ',' + quote(target))
        index_ref = quote(foreign) + '.ix_facts_tenant_company_count'
        oid = conn.execute(sa.text('SELECT cast(:name AS regclass)::oid'), {'name': index_ref}).scalar_one()
        conn.commit()
        conn.execution_options(isolation_level='AUTOCOMMIT')
        if invalid:
            with pytest.raises(sa.exc.IntegrityError):
                conn.exec_driver_sql('CREATE UNIQUE INDEX CONCURRENTLY ix_facts_tenant_company_count ON '
                                     + quote(target) + '.financial_facts(company_id)')
            conn.rollback()
            assert migration._invalid(conn)
            conn.rollback()
        run(conn, migration.upgrade)
        assert not migration._invalid(conn)
        indexes = {i['name']: i for i in sa.inspect(conn).get_indexes('financial_facts', schema=target)}
        assert indexes[migration.INDEX]['column_names'] == ['tenant_id', 'company_id']
        assert not indexes[migration.INDEX]['unique']
        assert conn.execute(sa.text('SELECT cast(:name AS regclass)::oid'), {'name': index_ref}).scalar_one() == oid
        assert conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 2
        conn.commit()
        run(conn, migration.downgrade)
        assert migration.INDEX not in {i['name'] for i in sa.inspect(conn).get_indexes('financial_facts', schema=target)}
        assert conn.execute(sa.text('SELECT cast(:name AS regclass)::oid'), {'name': index_ref}).scalar_one() == oid
        conn.commit()
    finally:
        conn.rollback()
        conn.exec_driver_sql('SET search_path TO ' + quote(target))
        conn.execute(DropSchema(foreign, cascade=True))
        conn.commit()
