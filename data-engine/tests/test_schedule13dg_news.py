from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.entities import Company, NewsEvent, Schedule13DGFiling, Tenant
from app.services.connectors.base import ConnectorItem, ConnectorResult
from app.services.connectors.form13dg import parse_schedule13dg
from app.services.feed_ingestion_service import FeedIngestionService
from app.services.schedule13dg_news import ensure_news
from app.services.schedule13dg_persistence import persist_filing

XML = (Path(__file__).parent / 'fixtures/schedule13g_asts_vanguard.xml').read_text()
FILING = dict(form='SCHEDULE 13G', accession_number='0002100119-26-001548',
              issuer_ticker='ASTS', filing_date='2026-10-30',
              document_url='https://www.sec.gov/Archives/edgar/data/1780312/000210011926001548/primary_doc.xml')

@pytest.fixture
def db():
    init_db()
    db = SessionLocal()
    db.query(NewsEvent).delete()
    db.query(Schedule13DGFiling).delete()
    company = db.scalar(select(Company).where(Company.ticker == 'ASTS'))
    if company is None:
        db.add(Company(ticker='ASTS', name='AST SpaceMobile', cik='1780312', exchange='NASDAQ', company_type='growth', valuation_model='dcf'))
    else:
        company.cik = '1780312'
    db.commit()
    yield db
    db.close()


def sec_poll(db):
    item = ConnectorItem(source='SEC', title='SCHEDULE 13G presentado ante la SEC',
                         url=FILING['document_url'].replace('/primary_doc', '/xslSCHEDULE_13G_X02/primary_doc'),
                         ticker='ASTS', metadata=FILING, headline_from_source=False)
    return FeedIngestionService().ingest_news_result(db, ConnectorResult(source='sec', items=[item]), ticker='ASTS')


def test_real_vanguard_fixture():
    parsed = parse_schedule13dg(XML)
    assert parsed['parsed_ok']
    assert parsed['aggregate_shares'] == 15330194
    assert parsed['percent_of_class'] == 5.11
    assert parsed['snapshot_date'] == '2026-09-30'
    assert 'Vanguard Capital Management' in parsed['holder_name']


@pytest.mark.parametrize('news_first', [True, False])
def test_both_publish_orders_one_event_no_alert_or_automatic_buy(db, news_first, monkeypatch):
    from app.models.entities import ResearchAlert, ThesisChange
    before = (db.query(ResearchAlert).count(), db.query(ThesisChange).count())
    def forbidden(*a, **kw):
        raise AssertionError('generic semantic/alert path must not run')
    monkeypatch.setattr('app.services.news_service.NewsService._analyze_news', forbidden)
    parsed = parse_schedule13dg(XML)
    if news_first:
        assert sec_poll(db)['created'] == 1
    persist_filing(db, FILING, parsed, raw_text=XML)
    db.commit()
    assert sec_poll(db)['created'] == 0
    persist_filing(db, FILING, parsed, raw_text=XML)
    db.commit()
    rows = db.scalars(select(NewsEvent)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.materiality_score == 6
    assert row.event_type == 'ownership_disclosure'
    assert row.metadata_['participation']['percent_of_class'] == 5.11
    assert row.title.startswith('Declaración de participación')
    assert 'Vanguard' in row.title
    assert row.requires_update is False and row.affected_thesis is False
    assert (db.query(ResearchAlert).count(), db.query(ThesisChange).count()) == before


def test_legacy_event_adopted_canonical_accession(db):
    company = db.scalar(select(Company).where(Company.ticker == 'ASTS'))
    db.add(NewsEvent(company_id=company.id, title='old title', source='SEC', url=FILING['document_url']))
    db.commit()
    assert ensure_news(db, FILING, parse_schedule13dg(XML))['created'] is False
    assert db.query(NewsEvent).count() == 1
    assert db.scalar(select(NewsEvent)).sec_filing_identity.endswith(FILING['accession_number'])


def test_missing_fields_not_invented(db):
    result = ensure_news(db, FILING, {'parsed_ok': False})
    row = db.get(NewsEvent, result['event_id'])
    assert 'Acciones declaradas' not in row.summary and 'Participación:' not in row.summary
    assert row.title == 'Declaración de participación (SCHEDULE 13G)'


@pytest.mark.parametrize('changes', [dict(accession_number='bad'), dict(issuer_ticker='UNKNOWN'),
    dict(document_url='https://example.com/anything'), dict(document_url=FILING['document_url'].replace('1780312','1234')),
    dict(document_url=FILING['document_url'].replace('001548','001549'))])
def test_invalid_or_wrong_issuer_not_published(db, changes):
    assert ensure_news(db, {**FILING, **changes})['created'] is False
    assert db.query(NewsEvent).count() == 0


def test_amendment_separate_and_tenants_isolated(db):
    tenants = []
    for external in ['13dg-news-A', '13dg-news-B']:
        tenant = db.scalar(select(Tenant).where(Tenant.external_id == external))
        if tenant is None:
            tenant = Tenant(external_id=external)
            db.add(tenant)
            db.flush()
        tenants.append(tenant.id)
    for tenant in tenants:
        ensure_news(db, FILING, tenant_id=tenant)
    amended = {**FILING, 'form': 'SCHEDULE 13G/A', 'accession_number': '0002100119-26-001549',
               'document_url': FILING['document_url'].replace('001548','001549')}
    ensure_news(db, amended, tenant_id=tenants[0])
    db.commit()
    assert db.query(NewsEvent).count() == 3


def test_unique_identity_rejects_duplicate_at_database_level(db):
    from sqlalchemy.exc import IntegrityError
    ensure_news(db, FILING)
    db.commit()
    row = db.scalar(select(NewsEvent))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(NewsEvent(company_id=row.company_id, title='concurrent duplicate', source='SEC',
                         sec_filing_identity=row.sec_filing_identity))
        db.flush()
    assert db.query(NewsEvent).count() == 1


def test_migration_roundtrip_preserves_existing_news():
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    path = Path(__file__).parents[1] / 'alembic/versions/0104_sec_filing_news_identity.py'
    spec = importlib.util.spec_from_file_location('migration_0104', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE news_events (id INTEGER PRIMARY KEY, title TEXT NOT NULL)'))
        conn.execute(text("INSERT INTO news_events VALUES (1, 'legacy')"))
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        assert 'sec_filing_identity' in {c['name'] for c in inspect(conn).get_columns('news_events')}
        assert conn.execute(text('SELECT title,sec_filing_identity FROM news_events')).one() == ('legacy', None)
        module.downgrade()
        assert conn.execute(text('SELECT title FROM news_events')).scalar_one() == 'legacy'
    engine.dispose()


def test_bad_date_and_parsed_wrong_issuer_rejected(db):
    assert ensure_news(db, {**FILING, 'filing_date': ''})['reason'] == 'invalid_date'
    assert ensure_news(db, FILING, {'issuer_cik': '1234'})['reason'] == 'issuer_mismatch'
    assert db.query(NewsEvent).count() == 0


def test_unparsed_retry_cannot_erase_verified_values(db):
    ensure_news(db, FILING, parse_schedule13dg(XML))
    ensure_news(db, FILING, {'parsed_ok': False})
    assert db.scalar(select(NewsEvent)).metadata_['participation']['aggregate_shares'] == 15330194
