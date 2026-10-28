"""Synthetic-only receipts and concurrency regression tests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import CashBalance, IbkrRawRow, Position
from app.services import ibkr_connection_service as service
from tests.test_ibkr_tenant_connection import report, save, settings, tenant


def test_receipt_survives_session_and_reimport_has_no_duplicate_rows(monkeypatch):
    import app.services.market_close_sync as prices
    monkeypatch.setattr(prices, 'enqueue_price_backfills', lambda *a, **k: 0)
    init_db()
    with SessionLocal() as db:
        owner = tenant(db)
        save(db)
        _, _, account, revision = service.credentials(db, settings())
        first = service.import_report(db, report(), account, revision)['last_sync']
        second = service.import_report(db, report(), account, revision)['last_sync']
        assert first['id'] != second['id']
        assert first['period_end'] == second['period_end']
        assert second['result'] == 'partial'
        assert second['counts']['raw_rows_stored'] == 0
        assert second['counts']['raw_rows_already_present'] == 2
        assert second['error_code'] is None
        assert len(db.scalars(select(Position)).all()) == 1
        assert len(db.scalars(select(CashBalance)).all()) == 1
        assert len(db.scalars(select(IbkrRawRow)).all()) == 2
    with SessionLocal() as db:
        db.info['tenant_id'] = owner
        assert service.view(db)['last_sync']['id'] == second['id']
        tenant(db)
        assert service.view(db)['last_sync'] is None


def test_two_concurrent_sync_leases_only_one_winner():
    init_db()
    with SessionLocal() as db:
        owner = tenant(db)
        save(db)
    acquired = Barrier(2)
    release = Barrier(2)
    def hold():
        with SessionLocal() as db:
            db.info['tenant_id'] = owner
            with service.sync_lease(db):
                acquired.wait(timeout=10)
                release.wait(timeout=10)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold)
        acquired.wait(timeout=10)
        try:
            with SessionLocal() as db:
                db.info['tenant_id'] = owner
                with pytest.raises(service.SyncBusy):
                    with service.sync_lease(db):
                        pytest.fail('overlapping sync entered')
        finally:
            release.wait(timeout=10)
        future.result(timeout=10)
    with SessionLocal() as db:
        db.info['tenant_id'] = owner
        with service.sync_lease(db):
            pass


def test_failed_receipt_is_safe_and_old_revision_cannot_change_new_connection():
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        revision = service.connection(db).revision
        receipt_id = service.start_receipt(db, revision=revision)
        save(db)
        service.record_failure(db, revision=revision, receipt_id=receipt_id)
        status = service.view(db)
        assert status['status'] == 'connected'
        assert status['last_sync']['result'] == 'error'
        assert status['last_sync']['revision'] == revision
        assert status['last_sync']['error_code'] == 'sync_failed'
        assert '1234567890123456' not in str(status)


def test_lease_released_on_exception_and_other_tenant_is_independent():
    init_db()
    with SessionLocal() as db, SessionLocal() as other:
        db.info['tenant_id'] = 800001
        other.info['tenant_id'] = 800002
        with pytest.raises(RuntimeError):
            with service.sync_lease(db):
                with service.sync_lease(other):
                    raise RuntimeError('synthetic crash')
        with service.sync_lease(db):
            pass


def test_postgres_cross_session_race_and_commits():
    """Opt-in, isolated local PostgreSQL only. Never points at production."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    url = os.environ.get('IBKR_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('set IBKR_TEST_POSTGRES_URL to an isolated PostgreSQL')
    engine = create_engine(url)
    barrier = Barrier(2)
    release = Barrier(2)
    def owner():
        with Session(engine) as db:
            db.info['tenant_id'] = 800001
            with service.sync_lease(db):
                db.commit()
                db.rollback()
                barrier.wait(timeout=10)
                release.wait(timeout=10)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(owner)
            barrier.wait(timeout=10)
            try:
                with Session(engine) as db:
                    db.info['tenant_id'] = 800001
                    with pytest.raises(service.SyncBusy):
                        with service.sync_lease(db):
                            pytest.fail('same tenant entered after owner commit')
                    db.info['tenant_id'] = 800002
                    with service.sync_lease(db):
                        pass
            finally:
                release.wait(timeout=10)
            task.result(timeout=10)
        with Session(engine) as db:
            db.info['tenant_id'] = 800001
            with pytest.raises(RuntimeError):
                with service.sync_lease(db):
                    raise RuntimeError('synthetic crash')
            with service.sync_lease(db):
                pass
    finally:
        engine.dispose()


def test_receipt_counts_never_persist_raw_row_errors(monkeypatch):
    init_db()
    monkeypatch.setattr(service.IBKRImportService, 'import_flex_xml', lambda *a, **k: {
        'row_errors': ['secret-upstream-value'], 'rows_skipped': 2,
        'raw_payload': 'secret-xml', 'positions_imported': 1,
    })
    with SessionLocal() as db:
        tenant(db)
        save(db)
        _, _, account, revision = service.credentials(db, settings())
        result = service.import_report(db, report(), account, revision)
        assert result['last_sync']['counts'] == {'positions_imported': 1, 'rows_skipped': 2, 'row_errors': 1, 'reconcile_blocked': 0}
        assert 'secret' not in str(result)


def test_route_and_worker_share_lease_busy_does_not_download(monkeypatch):
    import asyncio
    from contextlib import contextmanager

    from fastapi import HTTPException

    from app.api.routes import settings as routes
    from app.workers import dramatiq_app as workers
    init_db()
    calls = []
    monkeypatch.setattr(service, 'credentials', lambda *a: calls.append('credentials'))
    with SessionLocal() as db:
        owner = tenant(db)
        save(db)
        @contextmanager
        def session(*args):
            yield db
        monkeypatch.setattr(workers, '_session', session)
        with service.sync_lease(db):
            with pytest.raises(HTTPException) as caught:
                asyncio.run(routes.sync_ibkr_connection(db))
            assert caught.value.status_code == 409
            assert workers.sync_one_tenant_ibkr.fn(owner, 'synthetic-owner')['status'] == 'busy'
        assert calls == []
        assert service.view(db)['last_sync'] is None


def test_receipt_migration_adopts_existing_model_and_rejects_drift(monkeypatch):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    path = Path(__file__).parents[1] / 'alembic/versions/0097_ibkr_sync_receipts.py'
    spec = importlib.util.spec_from_file_location('ibkr_receipts_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with create_engine('sqlite://').begin() as conn:
        monkeypatch.setattr(module, 'op', Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()
        assert inspect(conn).has_table('ibkr_sync_receipts')
        conn.exec_driver_sql('ALTER TABLE ibkr_sync_receipts ADD COLUMN drift INTEGER')
        with pytest.raises(RuntimeError, match='schema mismatch'):
            module.upgrade()
        module.downgrade()
        assert not inspect(conn).has_table('ibkr_sync_receipts')


def test_reimport_receipt_covers_trade_ledger_and_period(monkeypatch):
    from datetime import date

    import app.services.market_close_sync as prices
    from app.models import Transaction
    monkeypatch.setattr(prices, 'enqueue_price_backfills', lambda *a, **k: 0)
    today = date.today().strftime('%Y%m%d')
    xml = report().replace('toDate=', f'fromDate="{today}" toDate=').replace(
        '</FlexStatement>',
        f'<Trades><Trade accountId="U123456" assetCategory="STK" symbol="TEST" currency="USD" buySell="BUY" quantity="2" tradePrice="9" tradeDate="{today}" tradeID="synthetic-trade-1" /></Trades></FlexStatement>',
    )
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        _, _, account, revision = service.credentials(db, settings())
        first = service.import_report(db, xml, account, revision)['last_sync']
        second = service.import_report(db, xml, account, revision)['last_sync']
        assert first['period_start'] == second['period_end'] == date.today()
        assert first['counts']['trades_imported'] == 1
        assert second['counts']['trades_imported'] == 0
        assert second['counts']['raw_rows_stored'] == 0
        assert len(db.scalars(select(Transaction)).all()) == 1
        assert len(db.scalars(select(IbkrRawRow)).all()) == 3


def test_download_failure_has_durable_receipt(monkeypatch):
    import asyncio

    from fastapi import HTTPException

    from app.api.routes import settings as routes
    init_db()
    monkeypatch.setattr(routes, 'get_settings', settings)
    async def fail(*args):
        raise service.ConnectionError('fixed synthetic failure')
    monkeypatch.setattr(service, 'download', fail)
    with SessionLocal() as db:
        owner = tenant(db)
        save(db)
        with pytest.raises(HTTPException):
            asyncio.run(routes.sync_ibkr_connection(db))
    with SessionLocal() as db:
        db.info['tenant_id'] = owner
        receipt = service.view(db)['last_sync']
        assert receipt['result'] == 'error'
        assert receipt['error_code'] == 'sync_failed'
        assert receipt['finished_at'] is not None
        assert receipt['period_end'] is None
