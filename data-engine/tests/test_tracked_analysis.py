from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Tenant, WorkflowRun
from app.services import tracked_analysis as tracked
from app.services.thesis_job_service import WORKFLOW_NAME


def test_daily_dedupe_and_quota_tenant_scope_and_batched_status(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=1, external_id='t1'), Tenant(id=2, external_id='t2')])
        db.commit()
        db.info.update(tenant_id=1, user_id='u1')
        calls = []
        def enqueue(db, ticker, **kwargs):
            calls.append((ticker, kwargs))
            db.add(WorkflowRun(tenant_id=db.info['tenant_id'], workflow_name=WORKFLOW_NAME, status='succeeded', input_payload={'ticker':ticker, 'tracked':True}, result_payload={'status':'insufficient_data'}, finished_at=datetime.now(UTC)))
            db.commit()
        monkeypatch.setattr(tracked, 'enqueue_generation', enqueue)
        monkeypatch.setattr(tracked, 'DAILY_LIMIT', 2)
        tracked.enqueue_tracked_analysis(db, 'AAPL')
        tracked.enqueue_tracked_analysis(db, 'AAPL')
        tracked.enqueue_tracked_analysis(db, 'MSFT')
        tracked.enqueue_tracked_analysis(db, 'NVDA')
        assert len(calls) == 2
        assert calls[0][1]['tracked'] is True
        assert calls[0][1]['request_id'].startswith('tracked:')
        states = tracked.tracked_statuses(db, ['AAPL','MSFT'])
        assert states['AAPL']['thesis_status'] == 'insufficient_data'
        assert states['MSFT']['as_of']
        db.info.update(tenant_id=2, user_id='u2')
        assert tracked.tracked_statuses(db, ['AAPL']) == {}
        tracked.enqueue_tracked_analysis(db, 'NVDA')
        assert len(calls) == 3
        db.info.clear()
        tracked.enqueue_tracked_analysis(db, 'UNKNOWN')
        assert len(calls) == 3
        assert len(db.scalars(select(WorkflowRun)).all()) == 3
    engine.dispose()
