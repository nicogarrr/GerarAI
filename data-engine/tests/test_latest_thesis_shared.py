"""One highest-version rule across chat, graph, invalidation and journal."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Tenant, ThesisVersion
from app.models.entities import Base
from app.services.chat_service import ChatService
from app.services.claim_scope import latest_thesis_version
from app.services.fundamental_review_service import DecisionJournalService
from app.services.thesis_graph_service import ThesisGraphService
from app.services.thesis_invalidation_rules import latest_thesis


def test_shared_latest_rule_keeps_drafts_and_tenant_scope():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        a, b = Tenant(external_id='latest-a'), Tenant(external_id='latest-b')
        db.add_all([a, b]); db.flush()
        company = Company(ticker='LATEST', name='Fixture', exchange='TEST',
                          company_type='standard', valuation_model='standard_dcf')
        db.add(company); db.flush()
        for tenant, version, status in [(a, 1, 'published'), (a, 2, 'draft'), (b, 99, 'published')]:
            db.info['tenant_id'] = tenant.id
            db.add(ThesisVersion(tenant_id=tenant.id, company_id=company.id,
                                version=version, status=status, thesis_markdown='# Fixture', executive_summary='Fixture'))
            db.flush()
        for tenant, expected in [(a, 2), (b, 99)]:
            db.info['tenant_id'] = tenant.id
            for thesis in [latest_thesis_version(db, company), latest_thesis_version(db, company.id),
                           latest_thesis(db, company.id), ThesisGraphService().latest_thesis(db, company),
                           ChatService._latest_thesis(None, db, company)]:
                assert thesis is not None
                assert (thesis.tenant_id, thesis.version) == (tenant.id, expected)
            entry = DecisionJournalService().create(db, company, decision='watch',
                                                    rationale='Fixture', what_must_be_true=[])
            assert entry.metadata_['thesis_version'] == expected
