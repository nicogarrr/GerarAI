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


def _company(db, ticker):
    from app.models import Company

    c = Company(ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD", sector="S",
                industry="I", company_type="c", valuation_model="unassigned",
                special_sources=[], special_risks=[], factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _thesis(db, company, status, days_ago):
    from datetime import timedelta

    from app.models import ThesisVersion

    db.add(ThesisVersion(tenant_id=db.info["tenant_id"], company_id=company.id, version=1, status=status,
                         thesis_markdown="x", executive_summary="x",
                         created_at=datetime.now(UTC) - timedelta(days=days_ago)))
    db.commit()


def test_backfill_watchlist_encola_lo_que_falta_por_tenant(monkeypatch):
    """Owner 3-nov-2026: toda la watchlist con tesis en segundo plano, para cada usuario."""
    from app.models import WatchItem

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=1, external_id='t1'), Tenant(id=2, external_id='t2')])
        db.commit()
        db.info.update(tenant_id=1, user_id='u1')
        calls = []

        def enqueue(db, ticker, **kwargs):
            calls.append((db.info['tenant_id'], ticker))
            db.add(WorkflowRun(tenant_id=db.info['tenant_id'], workflow_name=WORKFLOW_NAME, status='queued',
                               input_payload={'ticker': ticker, 'tracked': True}))
            db.commit()

        monkeypatch.setattr(tracked, 'enqueue_generation', enqueue)
        final, old_insuff, new_insuff = _company(db, 'AAPL'), _company(db, 'AENA'), _company(db, 'EBRO')
        _company(db, 'ABCL')
        _thesis(db, final, 'final', 1)
        _thesis(db, old_insuff, 'insufficient_data', 5)
        _thesis(db, new_insuff, 'insufficient_data', 1)
        for symbol in ('AAPL', 'AENA', 'EBRO', 'ABCL'):
            db.add(WatchItem(tenant_id=1, symbol=symbol))
        db.commit()
        db.info.update(tenant_id=2, user_id='u2')
        db.add(WatchItem(tenant_id=2, symbol='MSFT'))
        db.commit()
        db.info.update(tenant_id=1, user_id='u1')

        out = tracked.backfill_watchlist_theses(db)
        assert sorted(out['enqueued']) == ['ABCL', 'AENA']
        assert out['skipped'] == {'AAPL': 'tesis_final', 'EBRO': 'insuficiente_reciente'}
        assert calls == [(1, 'AENA'), (1, 'ABCL')]
        # segunda pasada el mismo dia: nada nuevo (ya hay corrida activa)
        again = tracked.backfill_watchlist_theses(db)
        assert again['enqueued'] == [] and again['skipped']['ABCL'] == 'en_curso'
        # el otro usuario tiene su propia pasada
        db.info.update(tenant_id=2, user_id='u2')
        other = tracked.backfill_watchlist_theses(db)
        assert other['enqueued'] == ['MSFT'] and calls[-1] == (2, 'MSFT')
    engine.dispose()


def test_paused_symbol_blocks_direct_and_backfill_enqueue_for_only_its_tenant(monkeypatch):
    from app.models import WatchItem

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=1, external_id='paused1'), Tenant(id=2, external_id='paused2')])
        db.commit()
        db.info.update(tenant_id=1, user_id='u1')
        db.add(WatchItem(tenant_id=1, symbol='GFL', company='GFL', auto_analysis_enabled=False))
        db.commit()
        calls = []
        monkeypatch.setattr(tracked, 'enqueue_generation', lambda db, ticker, **kwargs: calls.append(ticker))
        tracked.enqueue_tracked_analysis(db, 'GFL')
        assert calls == []
        result = tracked.backfill_watchlist_theses(db)
        assert result['skipped']['GFL'] == 'analisis_pausado'
        assert calls == []
        db.info.update(tenant_id=2, user_id='u2')
        tracked.enqueue_tracked_analysis(db, 'GFL')
        assert calls == ['GFL']
    engine.dispose()


def test_missing_inputs_batched_constant_queries_and_tenant_isolation():
    from sqlalchemy import event

    from app.models import FundamentalModelVersion

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=1, external_id='batch1'), Tenant(id=2, external_id='batch2')])
        db.commit()
        db.info['tenant_id'] = 1
        tickers = [f'BATCH{i}' for i in range(12)]
        for i, ticker in enumerate(tickers):
            company = _company(db, ticker)
            db.add(WorkflowRun(tenant_id=1, workflow_name=WORKFLOW_NAME, status='succeeded',
                input_payload={'ticker': ticker}, result_payload={'status': 'insufficient_data'}))
            if i == 11:  # Known company without model retains None, not [].
                continue
            for tenant, version, inputs in ((1, 1, ['old']), (1, 2, ['wacc', 'revenue']),
                                             (2, 99, ['private-other-tenant'])):
                db.flush()
                db.info['tenant_id'] = tenant
                db.add(FundamentalModelVersion(tenant_id=tenant, company_id=company.id,
                    version=version, engine_version='fixture', algorithm_version='fixture',
                    framework_key='dcf', horizon_years=5, status='insufficient_data',
                    publishable=False, input_fingerprint=f'i-{version}', forecast_fingerprint='f',
                    market_snapshot_fingerprint='m', valuation_snapshot_fingerprint='v',
                    model_snapshot={'missing_inputs': inputs, 'valuation': {
                        'excluded_inputs': [{'metric': 'revenue', 'reason': 'present_not_usable'}]}}))
                db.flush()
                db.info['tenant_id'] = 1
        db.commit()
        queries = []
        def record(conn, cursor, sql, params, context, many):
            queries.append(sql)
        event.listen(engine, 'before_cursor_execute', record)
        for wanted in (tickers[:1], tickers):
            queries.clear()
            states = tracked.tracked_statuses(db, wanted)
            assert len(queries) == 3  # workflows, companies, latest models
            assert sum('fundamental_model_versions' in q for q in queries) == 1
            assert states[tickers[0]]['missing_inputs'] == ['wacc']
        assert states[tickers[-1]]['missing_inputs'] is None
        db.info['tenant_id'] = 2
        assert tracked.tracked_statuses(db, tickers) == {}
    engine.dispose()


def test_backfill_empty_unauthenticated_limit_and_deduplicated(monkeypatch):
    from app.models import WatchItem

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert tracked.backfill_watchlist_theses(db)['reason'] == 'sin tenant'
        assert tracked.tracked_statuses(db, ['ANY']) == {}
        db.add(Tenant(id=1, external_id='empty'))
        db.commit()
        db.info['tenant_id'] = 1
        assert tracked.backfill_watchlist_theses(db)['enqueued'] == []
        db.add(WatchItem(tenant_id=1, symbol='ANY'))
        db.commit()
        assert tracked.backfill_watchlist_theses(db, limit=0)['skipped'] == {'ANY': 'tope_diario'}
        monkeypatch.setattr(tracked, 'enqueue_tracked_analysis', lambda *a: None)
        assert tracked.backfill_watchlist_theses(db)['skipped'] == {'ANY': 'deduplicado'}
    engine.dispose()
