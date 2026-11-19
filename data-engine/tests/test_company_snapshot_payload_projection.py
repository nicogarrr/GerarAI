"""Bootstrap payloads stay unread and cannot become N+1 deferred loads."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, desc, event, inspect, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

import app.models as models
from app.models import FundamentalModelVersion, ThesisVersion, ValuationModel
from app.services.company_snapshot_service import CompanySnapshotService
from tests.test_company_snapshot_batch import _company, _fill


@pytest.fixture
def db():
    url = os.environ.get('SNAPSHOT_TEST_PG_URL')
    raw = create_engine(url or 'sqlite:///:memory:')
    schema = 'snapshot_test_' + uuid4().hex
    if url:
        with raw.begin() as conn:
            conn.execute(CreateSchema(schema))
        engine = raw.execution_options(schema_translate_map={None: schema})
    else:
        engine = raw
    tables = {getattr(models, name).__table__ for name in (
        'Company', 'Tenant', 'ThesisVersion', 'FundamentalModelVersion', 'ValuationModel',
        'ThesisChange', 'ResearchReview', 'NewsEvent', 'Document', 'FinancialFact',
        'CalculatedMetric', 'Claim', 'ResearchAlert', 'Position')}
    while True:
        count = len(tables)
        tables.update(fk.column.table for table in list(tables) for fk in table.foreign_keys)
        if len(tables) == count:
            break
    try:
        models.Company.metadata.create_all(engine, tables=list(tables))
        with Session(engine) as session:
            session.add(models.Tenant(id=1, external_id='snapshot-fixture'))
            session.commit()
            session.info['tenant_id'] = 1
            yield session
    finally:
        if url:
            with raw.begin() as conn:
                conn.execute(DropSchema(schema, cascade=True))
        raw.dispose()

PAYLOADS = {ThesisVersion: ('thesis_markdown', 'narrative_sections', 'invalidation_rules'),
            FundamentalModelVersion: ('model_snapshot',), ValuationModel: ('calculation_trace',)}


@pytest.mark.parametrize('entity', list(PAYLOADS))
def test_latest_bootstrap_omits_unused_payload_and_raises_instead_of_lazy_loading(db, entity):
    company = _company(db, 'QA')
    _fill(db, company, thesis_versions=2, changes=0)
    cid = company.id
    db.expunge_all()
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        latest = CompanySnapshotService._latest_by_company(db, entity, [cid], desc(entity.version))[cid]
        assert latest.version == 2
        assert len(statements) == 1
        outer_select = statements[0].split('FROM (', 1)[0]
        for name in PAYLOADS[entity]:
            assert name not in outer_select
            assert name in inspect(latest).unloaded
            with pytest.raises(InvalidRequestError, match='raiseload'):
                getattr(latest, name)
        assert len(statements) == 1
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)


@pytest.mark.parametrize('publishable', [False, True])
@pytest.mark.parametrize('status', ['published', 'draft'])
def test_fresh_batch_payload_equals_full_single_including_publication_gate(db, publishable, status):
    company = _company(db, 'QA')
    cid = company.id
    _fill(db, company, thesis_versions=2, changes=2)
    thesis = db.scalar(select(ThesisVersion).where(ThesisVersion.company_id == cid,
        ThesisVersion.version == 2))
    model = db.scalar(select(FundamentalModelVersion).where(FundamentalModelVersion.company_id == cid,
        FundamentalModelVersion.version == 2))
    valuation = db.scalar(select(ValuationModel).where(ValuationModel.company_id == cid,
        ValuationModel.version == 2))
    thesis.status = status
    thesis.thesis_markdown = 'discarded ' * 10000
    thesis.narrative_sections = [{'unused': 'discarded'}]
    thesis.invalidation_rules = [{'unused': 'discarded'}]
    thesis.valuation_basis = {'model_input_fingerprint': model.input_fingerprint}
    thesis.hypothesis = 'Visible hypothesis'
    thesis.catalysts = [{'title': 'Visible catalyst'}]
    thesis.invalidation_criteria = ['Visible criterion']
    model.publishable = publishable
    model.model_snapshot = {'unused': 'discarded' * 10000}
    valuation.calculation_trace = {'unused': 'discarded' * 10000}
    db.commit()
    service = CompanySnapshotService()
    expected = service.build(db, company).model_dump(mode='json')
    db.expunge_all()
    company = db.get(type(company), cid)
    actual = service.build_many(db, [company])[cid].model_dump(mode='json')
    assert actual == expected


def test_partial_bootstrap_load_does_not_erase_archived_payload_on_write(db):
    company = _company(db, 'QA')
    _fill(db, company, thesis_versions=1, changes=0)
    cid = company.id
    db.expunge_all()
    row = CompanySnapshotService._latest_by_company(db, ThesisVersion, [cid], desc(ThesisVersion.version))[cid]
    row.rating = 'hold'
    db.commit()
    db.expunge_all()
    full = db.scalar(select(ThesisVersion).where(ThesisVersion.company_id == cid))
    assert full.thesis_markdown == '# T'
    assert full.rating == 'hold'
