"""SEC refresh repairs missing master identity, never from unchecked payloads."""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services import financial_ingestion_service as ingestion


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.info['tenant_id'] = 'test'
        yield session
    engine.dispose()


def _setup(db, monkeypatch, *, resolved='0001571283', payload=1571283,
           sec_name='Rexford Industrial Realty, Inc.', name='Rexford Industrial Realty Inc',
           card=None, exchange='NYSE'):
    class SEC:
        async def cik_for_ticker(self, ticker, entity_name=None):
            return resolved

        async def company_facts(self, cik):
            return {'cik': payload, 'entityName': sec_name, 'facts': {}}

        async def annual_report_anchors(self, cik):
            return {}

        async def index_accessions(self, cik):
            return set()

    monkeypatch.setattr(ingestion, 'SECClient', SEC)
    async def no_instance(*args, **kwargs):
        return None
    monkeypatch.setattr(ingestion, '_merge_latest_filing_instance', no_instance)
    monkeypatch.setattr(ingestion, '_free_data_snapshot', no_instance)
    company = Company(ticker='REXR', name=name, cik=card, exchange=exchange, currency='USD',
                      sector='Unknown', industry='Unknown', special_sources=[], special_risks=[],
                      factor_tags=[], company_type='research_candidate', valuation_model='unassigned')
    db.add(company)
    db.commit()
    return company


def _refresh(db, company):
    return asyncio.run(ingestion.FinancialIngestionService().refresh_from_sec(db=db, company=company))


def test_missing_master_cik_is_persisted_on_refresh(db, monkeypatch):
    company = _setup(db, monkeypatch)
    _refresh(db, company)
    assert company.cik == '0001571283'
    db.commit()
    db.expire_all()
    assert company.cik == '0001571283'


def test_unchanged_snapshot_still_repairs_identity(db, monkeypatch):
    company = _setup(db, monkeypatch)
    _refresh(db, company)
    company.cik = None
    db.commit()
    result = _refresh(db, company)
    assert result['status'] == 'unchanged'
    assert company.cik == '0001571283'


@pytest.mark.parametrize('kwargs', [
    {'payload': None}, {'payload': ''}, {'payload': 'invalid', 'resolved': 'invalid'},
    {'payload': '12345678901', 'resolved': '12345678901'},
    {'payload': 0, 'resolved': '0000000000'},
    {'sec_name': ''}, {'sec_name': 'Unrelated Software Widgets'},
    {'name': ''},
])
def test_unverified_identity_is_not_backfilled(db, monkeypatch, kwargs):
    company = _setup(db, monkeypatch, **kwargs)
    _refresh(db, company)
    assert company.cik is None


@pytest.mark.parametrize('kwargs', [
    {'payload': 123}, {'card': '0000000123'},
    {'exchange': 'LSE', 'sec_name': 'Unrelated Software Widgets'},
])
def test_rejected_identity_does_not_write_resolved_cik(db, monkeypatch, kwargs):
    company = _setup(db, monkeypatch, **kwargs)
    original = company.cik
    with pytest.raises(RuntimeError):
        _refresh(db, company)
    assert company.cik == original


def test_existing_equivalent_cik_is_not_reformatted(db, monkeypatch):
    company = _setup(db, monkeypatch, card='1571283')
    _refresh(db, company)
    assert company.cik == '1571283'


def test_unchanged_backfill_does_not_add_a_commit(db, monkeypatch):
    company = _setup(db, monkeypatch)
    _refresh(db, company)
    company.cik = None
    db.commit()
    assert _refresh(db, company)["status"] == "unchanged"
    assert company.cik == '0001571283'
    db.rollback()
    assert company.cik is None


@pytest.mark.parametrize('cik,card_name,sec_name', [
    (1571283, 'Rexford Industrial Realty Inc', 'Rexford Industrial Realty, Inc.'),
    (790051, 'Carlisle Companies Inc', 'CARLISLE COMPANIES INC'),
    (1383312, 'Broadridge Financial Solutions Inc', 'BROADRIDGE FINANCIAL SOLUTIONS, INC.'),
    (745308, 'St Joe Co', 'ST JOE CO'),
    (316709, 'SCHWAB (CHARLES) CORP', 'SCHWAB CHARLES CORP'),
    (64040, 'S&P Global Inc', 'S&P Global Inc.'),
])
def test_current_master_gap_name_shapes(db, monkeypatch, cik, card_name, sec_name):
    company = _setup(db, monkeypatch, resolved=str(cik), payload=cik,
                     name=card_name, sec_name=sec_name)
    _refresh(db, company)
    assert company.cik == str(cik).zfill(10)
