from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.models.entities import Base, Form144Notice, InsiderFiling, InsiderTransaction
from app.services import form144_monitor as monitor
from app.services.connectors import form144
from tests.test_0137_form144_migration import _create_table, _load
from tests.test_form144_feed import _notice
from tests.test_form144_monitor import REAL_144_XML, _db, _FakeClient


def test_adoption_rejects_foreign_key_to_wrong_tenant_column(monkeypatch):
    module=_load()
    engine=sa.create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE tenants (id INTEGER PRIMARY KEY, other INTEGER UNIQUE)')
        _create_table(conn)
        ops=Operations(MigrationContext.configure(conn))
        with ops.batch_alter_table('form144_notices') as batch:
            batch.create_unique_constraint('uq_existing',['tenant_id','accession_number'])
            batch.create_foreign_key('fk_wrong','tenants',['tenant_id'],['other'])
        monkeypatch.setattr(module,'op',ops)
        with pytest.raises(RuntimeError): module.upgrade()


def test_adopted_existing_data_survives_upgrade_downgrade(monkeypatch):
    module=_load()
    engine=sa.create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(_notice())
        db.commit()
    with engine.begin() as conn:
        monkeypatch.setattr(module,'op',Operations(MigrationContext.configure(conn)))
        module.upgrade()
        assert conn.scalar(sa.text('SELECT count(*) FROM form144_notices'))==1
        module.downgrade()
        assert sa.inspect(conn).has_table('form144_notices'),'downgrade deletes the adopted pre-existing table and its data'


def test_parser_rejects_other_edgar_submission_form():
    text='<edgarSubmission><headerData><submissionType>SC 13D</submissionType></headerData><formData><issuerInfo><issuerCik>0000849869</issuerCik></issuerInfo></formData></edgarSubmission>'
    assert form144.parse_form144_xml(text)['parsed_ok'] is False


def test_parser_hostile_entities_returns_unparsed_without_throwing():
    text='<!DOCTYPE edgarSubmission [<!ENTITY audit "synthetic">]><edgarSubmission><formData><remarks>&audit;</remarks></formData></edgarSubmission>'
    assert form144.parse_form144_xml(text)['parsed_ok'] is False


def test_download_budget_also_bounds_listing_requests(monkeypatch):
    db=_db()
    ciks={f'T{i}':str(100+i) for i in range(250)}
    monkeypatch.setattr(monitor,'resolve_ciks',lambda *a,**k:ciks)
    listing=Mock(return_value=[])
    monkeypatch.setattr(form144,'recent_form144_filings',listing)
    out=monitor.scan(db,tickers=list(ciks),max_new_fetches=10,delay_seconds=0)
    assert out['tickers_scanned']==250
    assert listing.call_count<=10, f'{listing.call_count} submissions requests with max_new_fetches=10'


def test_missing_issuer_is_not_published_as_verified_notice():
    db=_db()
    xml=REAL_144_XML.replace('<issuerCik>0000849869</issuerCik>','')
    out=monitor.scan(db,client=_FakeClient(),fetcher=lambda filing:xml,delay_seconds=0)
    row=db.scalar(sa.select(Form144Notice))
    assert row is None or row.status!='parsed','XML lacking issuer_cik accepted as parsed and attributed from listing'


def test_notice_never_creates_insider_operation():
    db=_db()
    monitor.scan(db,client=_FakeClient(),fetcher=lambda filing:REAL_144_XML,delay_seconds=0)
    assert db.scalar(sa.select(sa.func.count()).select_from(InsiderFiling))==0
    assert db.scalar(sa.select(sa.func.count()).select_from(InsiderTransaction))==0
