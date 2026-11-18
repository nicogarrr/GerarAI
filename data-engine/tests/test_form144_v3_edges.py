import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.entities import Base
from app.services import form144_monitor as monitor
from app.services.connectors import form144
from tests.test_0137_form144_migration import _load
from tests.test_form144_monitor import REAL_144_XML, _db


def test_provenance_table_is_not_alembic_drift(monkeypatch):
    module=_load()
    engine=sa.create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        monkeypatch.setattr(module,'op',Operations(MigrationContext.configure(conn)))
        module.upgrade()
        diffs=compare_metadata(MigrationContext.configure(conn),Base.metadata)
        assert not [d for d in diffs if d[0]=='remove_table' and d[1].name=='migration_table_provenance']


def test_deadline_checked_between_document_downloads(monkeypatch):
    db=_db()
    monkeypatch.setattr(monitor,'resolve_ciks',lambda *a,**k:{'ZZT':'0000849869'})
    filings=[{'accession_number':f'0000849869-26-{i:06d}','form':'144','filing_date':'2026-11-13','document_url':f'https://www.sec.gov/Archives/edgar/data/849869/000084986926{i:06d}/primary_doc.xml'} for i in range(10)]
    monkeypatch.setattr(form144,'recent_form144_filings',lambda *a,**k:filings)
    clock=[0.]
    monkeypatch.setattr(monitor.time,'monotonic',lambda:clock[0])
    def slow(filing):
        clock[0]+=100
        return REAL_144_XML
    out=monitor.scan(db,tickers=['ZZT'],fetcher=slow,delay_seconds=0,max_new_fetches=10,max_seconds=300)
    assert clock[0]<=400, f'elapsed {clock[0]} despite max_seconds=300; {out}'


def test_hostile_xml_download_returns_unparsed_not_throwing(monkeypatch):
    text='<!DOCTYPE edgarSubmission [<!ENTITY audit "synthetic">]><edgarSubmission><formData><remarks>&audit;</remarks></formData></edgarSubmission>'
    monkeypatch.setattr(form144,'_get_text',lambda *a,**k:text)
    text=form144.fetch_filing_xml('https://www.sec.gov/Archives/edgar/data/1/primary_doc.xml')
    assert form144.parse_form144_xml(text)['parsed_ok'] is False
