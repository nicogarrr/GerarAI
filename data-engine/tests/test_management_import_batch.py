"""Repeated call-claim imports must not do two SELECTs per existing promise."""
import math
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from app.models import CallClaim, Company, Document, FinancialFact, ManagementPromise, Tenant, Transcript
from app.models.entities import Base
from app.services.management_credibility_service import ManagementCredibilityService
from tests.test_management_credibility_service import _company


def seed(db, n):
    company = _company(db)
    transcript = Transcript(company_id=company.id, title='Call', period='FY2025')
    db.add(transcript)
    db.flush()
    for i in range(n):
        db.add(CallClaim(transcript_id=transcript.id, speaker=f'CEO {i}', speaker_role='ceo',
            claim=f'Revenue at least {100+i}', claim_type='guidance', metric='revenue',
            period='FY2026', created_at=datetime(2025, 1, 1, tzinfo=UTC)))
    db.commit()
    return company.id


@pytest.fixture
def engine():
    url = os.environ.get('MANAGEMENT_TEST_POSTGRES_URL')
    raw_engine = create_engine(url or 'sqlite:///:memory:')
    schema = 'management_review_' + uuid4().hex
    if url:
        with raw_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA {schema}'))
        engine = raw_engine.execution_options(schema_translate_map={None: schema})
        Base.metadata.create_all(engine, tables=[model.__table__ for model in
            [Tenant, Company, Document, FinancialFact, Transcript, CallClaim, ManagementPromise]])
    else:
        engine = raw_engine
        Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id=1, external_id='local'), Tenant(id=2, external_id='foreign')])
        db.commit()
    try:
        yield engine
    finally:
        if url:
            with raw_engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        raw_engine.dispose()


@pytest.mark.parametrize('expire', [True, False])
@pytest.mark.parametrize('n', [4, 40, 501])
def test_import_batch_read_budget_and_idempotence(engine, expire, n):
    with Session(engine, expire_on_commit=expire) as db:
        db.info['tenant_id'] = 1
        company_id = seed(db, n)
        service = ManagementCredibilityService()
        initial = service.import_call_claims(db, db.get(Company, company_id))
        assert len(initial) == n
        expected_ids = [row.id for row in initial]
        expected_claims = [row.call_claim_id for row in initial]
        assert expected_claims == sorted(expected_claims)
        assert all(row.status == 'open' and row.metadata_['source'] == 'call_claim' for row in initial)
        assert [row.target_value for row in initial] == list(range(100, 100+n))
    # A fresh session prevents identity-map masking of SELECTs.
    with Session(engine, expire_on_commit=expire) as db:
        db.info['tenant_id'] = 1
        company = db.get(Company, company_id)
        sql = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            sql.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            again = service.import_call_claims(db, company)
            # Access returned fields while counting to catch expired result rows.
            assert [row.id for row in again] == expected_ids
            assert [row.call_claim_id for row in again] == expected_claims
            assert all(row.promise and row.status == 'open' for row in again)
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert len([s for s in sql if s.lstrip().upper().startswith('SELECT')]) == 1 + 2 * math.ceil(n / 500)
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for s in sql)
        assert len(list(db.scalars(select(ManagementPromise)).all())) == n


def test_empty_batch_returns_empty_and_keeps_commit_contract(engine):
    with Session(engine) as db:
        db.info['tenant_id'] = 1
        cid = seed(db, 0)
        assert ManagementCredibilityService().import_call_claims(db, db.get(Company, cid)) == []


def test_import_does_not_read_foreign_tenant(engine):
    with Session(engine) as db:
        db.info['tenant_id'] = 1
        cid = seed(db, 3)
        # Global company, tenant-owned transcript/claims/promises.
        db.info['tenant_id'] = 2
        transcript = Transcript(company_id=cid, title='Foreign', period='FY2025')
        db.add(transcript)
        db.flush()
        db.add(CallClaim(transcript_id=transcript.id, speaker='Privado', speaker_role='ceo',
            claim='Private at least 999', claim_type='guidance', metric='revenue'))
        db.commit()
        db.info['tenant_id'] = 1
        result = ManagementCredibilityService().import_call_claims(db, db.get(Company, cid))
        assert len(result) == 3
        assert all('Private' not in row.promise for row in result)


def test_mixed_batch_keeps_existing_status_and_adds_only_new_claim(engine):
    with Session(engine) as db:
        db.info['tenant_id'] = 1
        cid = seed(db, 2)
        service = ManagementCredibilityService()
        first = service.import_call_claims(db, db.get(Company, cid))
        first[0].status = 'met'
        first[0].evidence = [{'custom': 'kept'}]
        existing_id = first[0].id
        transcript = db.scalar(select(Transcript).where(Transcript.company_id == cid))
        claim = CallClaim(transcript_id=transcript.id, speaker='CFO', speaker_role='cfo',
            claim='Revenue at least 999', claim_type='target', metric='revenue')
        db.add(claim)
        db.commit()
        result = service.import_call_claims(db, db.get(Company, cid))
        assert len(result) == 3
        assert result[0] is first[0]
        assert result[0].id == existing_id
        assert result[0].status == 'met'
        assert result[0].evidence == [{'custom': 'kept'}]
        assert result[-1].expected_period == 'unspecified'
        assert result[-1].target_value == 999
