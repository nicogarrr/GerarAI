from datetime import UTC, datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import DcaEvaluationRun
from app.models.entities import Base
from app.services import dca_manual_job

class Gate:
    owner = b'token'
    released = 0
    def get(self, key): return self.owner
    def eval(self, script, *args):
        if "EXPIRE" in script: return 1
        self.released += 1
        return 1
    def close(self): pass

@pytest.fixture
def env(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.info['tenant_id'] = 1
        row = DcaEvaluationRun(tenant_id=1, trigger='manual', status='queued',
            started_at=datetime.now(UTC), detail={'requested_symbols': ['A'], 'pending_remaining': 4})
        db.add(row); db.commit()
        gate = Gate()
        monkeypatch.setattr(dca_manual_job, 'redis_client', lambda: gate)
        yield db, row, gate
    engine.dispose()


def test_bounded_worker_persists_result_and_duplicate_does_not_evaluate_or_release(env, monkeypatch):
    db, row, gate = env
    calls = []
    def evaluate(db, *, symbols):
        calls.append(symbols)
        return dict(tracked=1, evaluated=1, alerted=[], skipped=[], errors=[], alerts_enabled=False, params_version='v1')
    monkeypatch.setattr('app.services.dca_signal_service.evaluate_watchlist', evaluate)
    assert dca_manual_job.run_manual_job(db, row.id, 'token')['status'] == 'ok'
    assert row.status == 'ok'
    assert row.detail['requested_symbols'] == ['A']
    assert row.detail['summary']['pending_remaining'] == 4
    assert dca_manual_job.run_manual_job(db, row.id, 'token') == {'status': 'ignored'}
    assert calls == [{'A'}]
    assert gate.released == 1


def test_cross_tenant_cannot_read_or_release_job(env):
    db, row, gate = env
    db.info['tenant_id'] = 2
    assert dca_manual_job.run_manual_job(db, row.id, 'token') == {'status': 'ignored'}
    assert row.status == 'queued'
    assert gate.released == 0


def test_expired_lease_does_not_evaluate(env, monkeypatch):
    db, row, gate = env
    gate.owner = b'new-owner'
    monkeypatch.setattr('app.services.dca_signal_service.evaluate_watchlist', lambda *a, **kw: pytest.fail('fetch forbidden'))
    with pytest.raises(RuntimeError): dca_manual_job.run_manual_job(db, row.id, 'token')
    assert row.status == 'error'
    assert gate.released == 0


def test_engine_failure_terminal_and_releases_owned_lease(env, monkeypatch):
    db, row, gate = env
    def fail(*a, **kw): raise ValueError('bad history')
    monkeypatch.setattr('app.services.dca_signal_service.evaluate_watchlist', fail)
    with pytest.raises(ValueError): dca_manual_job.run_manual_job(db, row.id, 'token')
    assert row.status == 'error'
    assert gate.released == 1


def test_oversized_receipt_fails_before_fetch(env, monkeypatch):
    db, row, gate = env
    row.detail = {'requested_symbols': [str(i) for i in range(11)]}; db.commit()
    monkeypatch.setattr('app.services.dca_signal_service.evaluate_watchlist', lambda *a, **kw: pytest.fail('fetch forbidden'))
    with pytest.raises(ValueError): dca_manual_job.run_manual_job(db, row.id, 'token')
    assert row.status == 'error'


def test_enqueue_is_202_and_never_fetches_then_status_is_scoped(env, monkeypatch):
    from app.api.routes import watchlist
    from app.workers.dramatiq_app import evaluate_manual_dca
    from app.services import dca_manual
    from fastapi import HTTPException
    db, row, gate = env
    db.info['user_id'] = 'u-1'
    sent = []
    monkeypatch.setattr(dca_manual, 'acquire_manual_gate', lambda *args: ('token', 0))
    monkeypatch.setattr(dca_manual, 'pending_symbols', lambda db: [str(i) for i in range(14)])
    monkeypatch.setattr(evaluate_manual_dca, 'send', lambda *args: sent.append(args))
    monkeypatch.setattr('app.services.dca_signal_service.evaluate_watchlist', lambda *a, **kw: pytest.fail('HTTP must not fetch'))
    receipt = watchlist.enqueue_manual_dca(db)
    assert receipt['requested'] == 10 and receipt['pending_remaining'] == 4
    assert len(sent) == 1
    assert watchlist.manual_dca_status(receipt['run_id'], db)['status'] == 'running'
    assert gate.released == 0
    db.info['tenant_id'] = 2
    with pytest.raises(HTTPException) as e: watchlist.manual_dca_status(receipt['run_id'], db)
    assert e.value.status_code == 404


def test_queue_failure_terminal_no_success_receipt(env, monkeypatch):
    from app.api.routes import watchlist
    from app.workers.dramatiq_app import evaluate_manual_dca
    from app.services import dca_manual
    from fastapi import HTTPException
    from sqlalchemy import select
    db, row, gate = env
    db.info['user_id'] = 'u-1'
    monkeypatch.setattr(dca_manual, 'acquire_manual_gate', lambda *args: ('token', 0))
    monkeypatch.setattr(dca_manual, 'pending_symbols', lambda db: ['A'])
    def fail(*a): raise RuntimeError('queue down')
    monkeypatch.setattr(evaluate_manual_dca, 'send', fail)
    with pytest.raises(HTTPException) as e: watchlist.enqueue_manual_dca(db)
    assert e.value.status_code == 503
    latest = db.scalar(select(DcaEvaluationRun).order_by(DcaEvaluationRun.id.desc()))
    assert latest.status == 'error'
    # Delivery may have landed despite send raising: lease expires naturally.
    assert gate.released == 0


def test_api_route_is_202():
    from app.api.routes.watchlist import router
    route = next(r for r in router.routes if r.path.endswith('/dca-signals/evaluate-async'))
    assert route.status_code == 202


def test_manual_lease_outlives_actor_limit():
    from app.services.dca_manual import LEASE_SECONDS
    from app.workers.dramatiq_app import evaluate_manual_dca
    assert LEASE_SECONDS * 1000 > evaluate_manual_dca.options['time_limit']


def test_queued_receipt_maps_to_running_until_stale(env):
    from app.services.dca_run_log import run_payload
    from datetime import timedelta
    db, row, gate = env
    assert run_payload(row)['status'] == 'running'
    assert run_payload(row, now=datetime.now(UTC) + timedelta(minutes=41))['status'] == 'interrupted'
