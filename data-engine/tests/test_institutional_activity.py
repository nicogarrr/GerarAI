"""Complete stored activity, missing filings, legacy readers and SELECT-only GET."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.ownership import router
from app.core.database import get_db
from app.models.public_market_data import PublicFinancialFact
from app.services import institutional_holders as ih
from app.services.institutional_activity import institutional_activity
from tests.test_institutional_holders import APPLE, _db, _parsed
from tests.test_institutional_new_positions import parsed_pair


def store(db, parses=None, *, legacy=False):
    parses = parses or _parsed()
    periods, _ = ih.ds.resolve_periods(parses)
    summary = ih.summarize(periods, APPLE, date(2026, 6, 30), date(2026, 3, 31))
    if legacy:
        summary.pop('activity')
    ih.persist(db, db.query(ih.Company).filter_by(ticker='AAPL').one(), summary, cusip=APPLE,
               dataset_url=parses[0].url, prior_url=parses[1].url, checksum='legacy' if legacy else 'activity')
    db.commit()


def test_every_manager_survives_and_nulls_mean_missing_filing():
    with _db() as db:
        store(db)
        result = institutional_activity(db, 'AAPL')
        assert result['status'] == 'ok' and result['total'] == 7
        rows = {r['name']: r for r in result['rows']}
        assert rows['Delta']['shares'] is None and rows['Delta']['change'] is None
        assert rows['Delta']['prev_shares'] == 20
        assert rows['Nu']['prev_shares'] is None and rows['Nu']['change'] is None
        assert rows['Gamma']['shares'] == 0 and rows['Gamma']['change'] == -30
        assert rows['Alpha']['shares'] == 150 and rows['Alpha']['reported_value_usd'] == 2
        assert all(r['company_ownership_pct'] is None for r in result['rows'])
        assert result['period'] == '2026-06-30' and result['prior_period'] == '2026-03-31'
        assert result['fetched_at'] and result['source_url']
        assert rows['Beta']['filing_url'].endswith('Q2-B2-index.htm')
        assert rows['Delta']['filing_url'] is None
        assert rows['Nu']['prev_filing_url'] is None


@pytest.mark.parametrize('status,total', [('all', 7), ('aumenta', 1), ('reduce', 1), ('nuevo', 1), ('vende_todo', 1)])
def test_filters_and_unknown_pages(status, total):
    with _db() as db:
        store(db)
        out = institutional_activity(db, 'AAPL', status=status, page_size=1)
        assert out['total'] == total and out['pages'] == total
        assert len(out['rows']) == 1
        assert institutional_activity(db, 'AAPL', status=status, page=999)['rows'] == []


def test_more_than_fifty_not_just_ten_and_stable_ties():
    from app.services.connectors import form13f_dataset as ds
    from tests.test_institutional_holders import OTHER, _info, _zip
    n = 63
    prev = _zip([f'P{i}\t15-MAY-2026\t13F-HR\t{i}\t31-MAR-2026' for i in range(1, n+1)], [],
                [_info(f'P{i}', OTHER, 1) for i in range(1, n+1)])
    cur = _zip([f'C{i}\t15-AUG-2026\t13F-HR\t{i}\t30-JUN-2026' for i in range(1, n+1)], [],
               [_info(f'C{i}', APPLE, 10) for i in range(1, n+1)])
    parses = [ds.parse_dataset(cur, {APPLE}, url='https://www.sec.gov/current.zip'), ds.parse_dataset(prev, {APPLE}, url='https://www.sec.gov/prior.zip')]
    with _db() as db:
        store(db, parses)
        pages = [institutional_activity(db, 'AAPL', page=p) for p in (1, 2, 3)]
        assert [len(p['rows']) for p in pages] == [25, 25, 13]
        ids = [r['cik'] for p in pages for r in p['rows']]
        assert ids == [str(i).zfill(10) for i in range(1, 64)]
        assert pages[0]['total'] == 63
        assert len(ih.institutional_holders(db, 'AAPL')['new_positions']['top_by_shares']) == 10
        assert not any(tag in ('role:all', 'new_role:all') for f in db.query(PublicFinancialFact) for tag in f.derived_from_refs)


def test_legacy_and_no_snapshot_are_unknown_not_zero():
    with _db() as db:
        assert institutional_activity(db, 'NOPE') is None
        assert institutional_activity(db, 'CGEO.L')['status'] == 'sin_identificador'
        missing = institutional_activity(db, 'AAPL')
        assert missing['status'] == 'sin_datos' and missing['total'] is None
        store(db, legacy=True)
        out = institutional_activity(db, 'AAPL')
        assert out['status'] == 'sin_detalle' and out['total'] is None and out['rows'] == []
        doc = db.query(ih.PublicSourceDocument).one()
        doc.listing_key = '13f:2026-06-30:594918104'
        db.commit()
        assert institutional_activity(db, 'AAPL')['status'] == 'sin_snapshot_vinculado'


def test_missing_reported_value_and_zero_results():
    parses = parsed_pair()
    parses[0].filings['C1'].values_usd[APPLE] = None
    with _db() as db:
        store(db, parses)
        out = institutional_activity(db, 'AAPL', status='nuevo')
        assert out['total'] == 14 and out['rows'][-1]['reported_value_usd'] is None
        empty = institutional_activity(db, 'AAPL', status='reduce')
        assert empty['status'] == 'ok' and empty['total'] == 0 and empty['rows'] == []


def test_route_read_only_and_validation():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    ih.Company.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ih.Company(ticker='AAPL', name='Apple', exchange='NASDAQ', company_type='mature', valuation_model='dcf', isin='US0378331005'))
        db.commit()
        store(db)
        app = FastAPI()
        app.include_router(router, prefix='/api/ownership')
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, 'before_cursor_execute', record)
        try:
            response = client.get('/api/ownership/institutions/AAPL/activity')
        finally:
            event.remove(db.bind, 'before_cursor_execute', record)
        assert response.status_code == 200 and response.json()['total'] == 7
        assert len(statements) == 4 and all(s.lstrip().upper().startswith('SELECT') for s in statements)
        assert client.get('/api/ownership/institutions/NOPE/activity').status_code == 404
        for query in ('page=0', 'page=-1', 'page_size=0', 'page_size=101', 'status=bad', 'page=x'):
            assert client.get('/api/ownership/institutions/AAPL/activity?'+query).status_code == 422


@pytest.mark.parametrize('args', [{'page': 0}, {'page_size': 101}, {'status': 'bad'}])
def test_service_rejects_invalid_arguments(args):
    with _db() as db, pytest.raises(ValueError):
        institutional_activity(db, 'AAPL', **args)
