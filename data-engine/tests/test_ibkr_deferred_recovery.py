"""Later-day retry selects only the latest, recent deferred report revision."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import IBKRConnection, IBKRSyncReceipt, Tenant
from app.workers import dramatiq_app as workers


@pytest.mark.parametrize('dedicated', [False, True])
def test_recovery_only_dispatches_current_recent_not_ready_for_active_owner(monkeypatch, dedicated):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    contexts = []
    with sessions() as db:
        def add(key, *, enabled=True, token='encrypted', status='error', code='not_ready',
                age=3, revision=1, result='error', active=True, later=None):
            owner = Tenant(external_id=key, name=key)
            db.add(owner)
            db.flush()
            db.add(IBKRConnection(tenant_id=owner.id, query_id='1', account_id='SYNTHETIC',
                                 token_ciphertext=token, enabled=enabled, revision=2, status=status))
            db.add(IBKRSyncReceipt(tenant_id=owner.id, revision=revision, result=result,
                                  error_code=code, started_at=now-timedelta(hours=age)))
            db.flush()
            if later:
                db.add(IBKRSyncReceipt(tenant_id=owner.id, revision=2, result=later,
                                      error_code=None, started_at=now))
                db.flush()
            if active:
                contexts.append((owner.id, key))
            return owner.id
        eligible = add('eligible', revision=2)
        add('credentials', code='credentials', revision=2)
        add('disabled', enabled=False, revision=2)
        add('no-token', token=None, revision=2)
        add('old-revision')
        add('old-attempt', age=25, revision=2)
        add('inactive-owner', active=False, revision=2)
        add('already-synced', status='synced', revision=2)
        add('newer-success', revision=2, later='synced')
        add('newer-running', revision=2, later='running')
        add('not-error', revision=2, result='partial')
        db.commit()
    import app.core.database as database
    monkeypatch.setattr(database, 'SessionLocal', sessions)
    monkeypatch.setattr(workers, 'tenant_contexts', lambda: contexts)
    monkeypatch.setattr(workers, 'get_settings', lambda: SimpleNamespace(ibkr_dedicated_sync_enabled=dedicated))
    calls = []
    selected = workers.sync_one_tenant_ibkr_dedicated if dedicated else workers.sync_one_tenant_ibkr
    other = workers.sync_one_tenant_ibkr if dedicated else workers.sync_one_tenant_ibkr_dedicated
    monkeypatch.setattr(selected, 'send', lambda *args: calls.append(args))
    monkeypatch.setattr(other, 'send', lambda *args: pytest.fail('wrong queue'))
    assert workers.retry_deferred_tenant_ibkr_connections.fn() == {'scheduled': 1}
    assert calls == [(eligible, 'eligible')]
    engine.dispose()


def test_recovery_schedule_exists_without_dedicated_worker(monkeypatch):
    from app.workers import scheduler as sched
    monkeypatch.setattr(sched.get_settings(), 'ibkr_dedicated_sync_enabled', False)
    scheduler = sched.build_scheduler(background=True)
    job = scheduler.get_job('tenant_ibkr_deferred_recovery')
    assert job.func.func is sched.coalesced_send
    assert job.func.args == (workers.retry_deferred_tenant_ibkr_connections,)
    fire = job.trigger.get_next_fire_time(None, datetime(2026, 11, 3, tzinfo=UTC))
    # Default scheduler jitter spreads cron dispatch by at most five minutes.
    assert fire.hour == 16
    assert 50 <= fire.minute < 56
    assert str(fire.tzinfo) == 'UTC'
    assert workers.retry_deferred_tenant_ibkr_connections.options['max_retries'] == 2


def test_recovery_database_failure_uses_normal_actor_error_handling(monkeypatch):
    import app.core.database as database
    def unavailable():
        raise RuntimeError('synthetic db failure')
    monkeypatch.setattr(database, 'SessionLocal', unavailable)
    calls = []
    monkeypatch.setattr(workers, '_handle_actor_error',
                        lambda actor, exc: calls.append((actor, str(exc))) or {'status': 'error'})
    assert workers.retry_deferred_tenant_ibkr_connections.fn() == {'status': 'error'}
    assert calls == [('retry_deferred_tenant_ibkr_connections', 'synthetic db failure')]
