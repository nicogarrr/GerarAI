"""Disposable-schema PostgreSQL regression: importer commits release row locks."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashBalance, IbkrRawRow, IBKRSyncReceipt, Position
from app.services import ibkr_connection_service as service
from tests.test_ibkr_tenant_connection import report, save, tenant


@pytest.fixture()
def pg_engine():
    url = os.environ.get('IBKR_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('requires disposable local PostgreSQL')
    parsed = make_url(url)
    if parsed.host not in {'localhost', '127.0.0.1', '::1'}:
        pytest.fail('IBKR regression only permits loopback PostgreSQL')
    schema = f'ibkr_race_{uuid4().hex}'
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


@pytest.mark.parametrize('mutation', ['disconnect', 'save'])
def test_committed_import_excludes_connection_mutations(pg_engine, monkeypatch, mutation):
    import app.services.market_close_sync as prices
    monkeypatch.setattr(prices, 'enqueue_price_backfills', lambda *a, **k: 0)
    with Session(pg_engine, expire_on_commit=False) as db:
        owner = tenant(db)
        save(db)
        revision = service.connection(db).revision
    committed, finish = Event(), Event()
    original = service.IBKRImportService.import_flex_xml

    def paused_import(self, db, xml, **kwargs):
        result = original(self, db, xml, **kwargs)
        # Model the real importer boundary explicitly, even if its internals change.
        db.commit()
        committed.set()
        assert finish.wait(15), 'mutation thread did not finish'
        return result

    monkeypatch.setattr(service.IBKRImportService, 'import_flex_xml', paused_import)

    def sync():
        with Session(pg_engine, expire_on_commit=False) as db:
            db.info['tenant_id'] = owner
            with service.sync_lease(db):
                return service.import_report(db, report(), 'U123456', revision)

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(sync)
        try:
            assert committed.wait(15), 'import did not reach commit'
            with Session(pg_engine, expire_on_commit=False) as db:
                db.info['tenant_id'] = owner
                with pytest.raises(service.SyncBusy):
                    service.disconnect(db) if mutation == 'disconnect' else save(db)
                db.rollback()
                row = service.connection(db)
                assert row.enabled and row.revision == revision
        finally:
            finish.set()
        result = task.result(timeout=15)
    assert result['last_sync']['result'] == 'partial'
    with Session(pg_engine, expire_on_commit=False) as db:
        db.info['tenant_id'] = owner
        # Retry after completion succeeds and cannot be undone by sync finalization.
        service.disconnect(db) if mutation == 'disconnect' else save(db)
    with Session(pg_engine) as db:
        db.info['tenant_id'] = owner
        row = service.connection(db)
        assert row.revision == revision + 1
        assert row.enabled == (mutation == 'save')
        assert bool(row.token_ciphertext) == (mutation == 'save')
        assert row.status == ('connected' if mutation == 'save' else 'disconnected')
        assert db.scalars(select(IBKRSyncReceipt)).one().result == 'partial'
        assert len(db.scalars(select(Position)).all()) == 1
        assert len(db.scalars(select(CashBalance)).all()) == 1
        assert len(db.scalars(select(IbkrRawRow)).all()) == 2


def test_migration_0096_postgres_repeated_downgrade_and_evidence_guard(pg_engine):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = Path(__file__).parents[1] / 'alembic/versions/0096_ibkr_raw_rows.py'
    spec = importlib.util.spec_from_file_location('m0096_pg', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pg_engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            module.upgrade()
            conn.execute(text("INSERT INTO ibkr_raw_rows(section, path, row_hash, payload, created_at, updated_at) VALUES ('Trades', 'Trades/Trade', 'synthetic', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match='retained evidence'):
                module.downgrade()
            assert conn.execute(text('SELECT count(*) FROM ibkr_raw_rows')).scalar() == 1
            # Synthetic fixture only; no application cleanup path is introduced.
            conn.execute(text('DELETE FROM ibkr_raw_rows'))
            module.downgrade()
            module.downgrade()
            assert not inspect(conn).has_table('ibkr_raw_rows')
            module.upgrade()
            module.upgrade()
            assert inspect(conn).has_table('ibkr_raw_rows')
