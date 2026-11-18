"""Mutation regressions for bounded lookup, real refresh, and claim identity."""
import re

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.models import CallClaim, Company, ManagementPromise, Transcript
from app.services.management_credibility_service import ManagementCredibilityService
from tests.test_management_import_batch import engine, seed  # noqa: F401


def test_existing_lookup_never_fetches_more_than_500_ids_per_query(engine):
    with Session(engine, expire_on_commit=False) as db:
        db.info['tenant_id'] = 1
        cid = seed(db, 501)
        company = db.get(Company, cid)
        service = ManagementCredibilityService()
        service.import_call_claims(db, company)
        sizes = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            match = re.search(r'management_promises\.call_claim_id IN \(([^)]*)\)', statement)
            if match:
                expanded = context.compiled_parameters[0]
                sizes.append(sum(key.startswith('call_claim_id_') for key in expanded))
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            assert len(service.import_call_claims(db, company)) == 501
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert sizes == [500, 1], f'lookup fetched duplicate/oversized batches: {sizes}'


def test_refresh_overwrites_identity_map_after_concurrent_post_commit_update(engine):
    with Session(engine, expire_on_commit=False) as db:
        db.info['tenant_id'] = 1
        cid = seed(db, 1)
        company = db.get(Company, cid)
        service = ManagementCredibilityService()
        [original] = service.import_call_claims(db, company)
        assert original.status == 'open'
        commits = []
        def concurrent_update(session):
            # Simulate another transaction between this commit and the refresh.
            # Core SQL bypasses the ORM identity map, which stays stale unless
            # populate_existing refreshes the real returned object.
            with engine.begin() as conn:
                conn.execute(update(ManagementPromise.__table__).where(
                    ManagementPromise.id == original.id).values(status='met'))
            commits.append(True)
        event.listen(db, 'after_commit', concurrent_update)
        try:
            [refreshed] = service.import_call_claims(db, company)
        finally:
            event.remove(db, 'after_commit', concurrent_update)
        assert commits == [True]
        assert refreshed is original
        assert refreshed.status == 'met'


def test_existing_map_uses_claim_id_not_promise_primary_key(engine):
    with Session(engine, expire_on_commit=False) as db:
        db.info['tenant_id'] = 1
        cid = seed(db, 0)
        transcript = db.scalar(select(Transcript).where(Transcript.company_id == cid))
        # This claim is never imported. It shifts the two independent sequences.
        db.add(CallClaim(transcript_id=transcript.id, speaker='CEO', speaker_role='ceo',
            claim='Non guidance', claim_type='other'))
        db.flush()
        for value in [100, 200]:
            db.add(CallClaim(transcript_id=transcript.id, speaker='CEO', speaker_role='ceo',
                claim=f'Revenue at least {value}', claim_type='target', metric='revenue'))
        db.commit()
        service = ManagementCredibilityService()
        company = db.get(Company, cid)
        first = service.import_call_claims(db, company)
        expected = [(row.id, row.call_claim_id, row.promise) for row in first]
        assert all(row.id != row.call_claim_id for row in first)
        again = service.import_call_claims(db, company)
        assert [(row.id, row.call_claim_id, row.promise) for row in again] == expected
        assert len(list(db.scalars(select(ManagementPromise)))) == 2
