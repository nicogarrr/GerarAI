"""The bounded document window must contain the latest reports, not oldest inserts."""
from app.services import filing_yoy_service as service
from tests.test_filing_yoy_service import db, doc  # noqa: F401


def test_candidate_limit_keeps_newest_reported_periods(db, monkeypatch):
    monkeypatch.setattr(service, 'MAX_DOCUMENTS', 2)
    doc(db, '2022-09-30', n=1)
    doc(db, '2023-09-30', n=2)
    before = doc(db, '2024-09-30', n=3)
    latest = doc(db, '2025-09-30', n=4)
    result = service.comparison(db, db.info['company_id'], '10-K', 1)
    assert result['current']['document_id'] == latest.id
    assert result['previous']['document_id'] == before.id


def test_invalid_candidates_do_not_exhaust_document_limit(db, monkeypatch):
    monkeypatch.setattr(service, 'MAX_DOCUMENTS', 2)
    doc(db, '2099-09-30', n=3)
    doc(db, '2026-09-30', n=4, url='https://example.com/fake')
    doc(db, 'invalid', n=5)
    doc(db, '2026-10-01', n=6, tenant=db.info['other_tenant'])
    prior = doc(db, '2024-09-30', n=1)
    current = doc(db, '2025-09-30', n=2)
    result = service.comparison(db, db.info['company_id'], '10-K', 1)
    assert result['total'] == 2
    assert result['current']['document_id'] == current.id
    assert result['previous']['document_id'] == prior.id


def test_document_cap_and_stable_tie_order_are_preserved(db, monkeypatch):
    monkeypatch.setattr(service, 'MAX_DOCUMENTS', 2)
    doc(db, '2023-09-30', n=1)
    earlier = doc(db, '2024-09-30', n=2)
    later = doc(db, '2024-09-30', n=3)
    first = service.comparison(db, db.info['company_id'], '10-K', 1)
    second = service.comparison(db, db.info['company_id'], '10-K', 2)
    assert first['total'] == second['total'] == 2
    assert first['current']['document_id'] == later.id
    assert second['current']['document_id'] == earlier.id
    assert service.comparison(db, db.info['company_id'], '10-K', 3)['status'] == 'insufficient_data'
