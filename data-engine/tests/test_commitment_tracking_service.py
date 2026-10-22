from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, ManagementPromise, ManagementPromiseNote
from app.services.commitment_tracking_service import (
    CommitmentTrackingError,
    CommitmentTrackingService,
    due_state,
)
from app.services.management_credibility_service import ManagementCredibilityService


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _session(engine, tenant):
    s = Session(engine)
    s.info["tenant_id"] = tenant
    return s


def _setup(db, criteria="Al menos 12 unidades entregadas"):
    company = Company(
        ticker="ACME", name="ACME", exchange="NYSE", currency="USD", sector="S", industry="I",
        company_type="holding", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    promise = ManagementCredibilityService().register(
        db, company, promise="We expect 12 units", promise_date=date(2030, 7, 1),
        expected_period="FY2031", metric=None, operator=None, target_value=None, unit=None,
        fulfillment_criteria=criteria, due_date=date(2031, 12, 31),
    )
    return company, promise


def test_verdict_requires_evidence_and_criteria():
    db = _session(_engine(), 1)
    _, promise = _setup(db)
    svc = CommitmentTrackingService()
    with pytest.raises(CommitmentTrackingError):  # link sin extracto
        svc.add_check(db, promise, outcome="met", checked_on=date(2032, 1, 5), evidence_url="https://x.invalid/a")
    with pytest.raises(CommitmentTrackingError):  # http
        svc.add_check(db, promise, outcome="met", checked_on=date(2032, 1, 5),
                      evidence_url="http://x.invalid/a", evidence_excerpt="12 units delivered")
    ok = svc.add_check(db, promise, outcome="met", checked_on=date(2032, 1, 5),
                       evidence_url="https://x.invalid/a", evidence_excerpt="12 units delivered", user_id="u1")
    assert ok.outcome == "met"
    _, no_criteria = _setup_second(db)
    with pytest.raises(CommitmentTrackingError, match="criterio"):
        svc.add_check(db, no_criteria, outcome="not_met", checked_on=date(2032, 1, 5),
                      evidence_url="https://x.invalid/a", evidence_excerpt="only 3")


def _setup_second(db):
    company = db.scalar(select(Company))
    promise = ManagementCredibilityService().register(
        db, company, promise="We aim for growth", promise_date=date(2030, 7, 1),
        expected_period="FY2031", metric=None, operator=None, target_value=None, unit=None,
    )
    return company, promise


def test_unknown_states_need_reason_and_overdue_is_not_missed():
    db = _session(_engine(), 1)
    _, promise = _setup(db)
    svc = CommitmentTrackingService()
    with pytest.raises(CommitmentTrackingError):
        svc.add_check(db, promise, outcome="not_verifiable", checked_on=date(2032, 1, 5))
    svc.add_check(db, promise, outcome="insufficient_evidence", checked_on=date(2032, 1, 5),
                  summary="La empresa no publico cifra de unidades")
    assert promise.status == "open"  # nada cambia solo
    assert due_state(promise, svc.checks(db, promise), date(2032, 6, 1)) == "overdue_unverified"
    assert due_state(promise, [], date(2031, 1, 1)) == "pending"
    promise.due_date = None
    assert due_state(promise, [], date(2032, 6, 1)) == "no_due_date"


def test_notes_are_private_per_user_and_per_tenant():
    engine = _engine()
    a = _session(engine, 1)
    _, promise = _setup(a)
    svc = CommitmentTrackingService()
    svc.add_note(a, promise, user_id="user-a", body="mi tesis privada")
    assert [n.body for n in svc.notes(a, promise, user_id="user-a")] == ["mi tesis privada"]
    assert svc.notes(a, promise, user_id="user-b") == []  # otro usuario, mismo tenant
    b = _session(engine, 2)
    rows = b.scalars(select(ManagementPromiseNote)).all()  # otro tenant
    assert rows == []
    b2 = _session(engine, 2)
    p_other = b2.get(ManagementPromise, promise.id)
    assert p_other is None
    with pytest.raises(CommitmentTrackingError):
        svc.add_note(a, promise, user_id="user-a", body="   ")


def test_dashboard_exposes_due_state_and_checks():
    db = _session(_engine(), 1)
    company, promise = _setup(db)
    promise.due_date = date.today() - timedelta(days=3)
    db.commit()
    dash = ManagementCredibilityService().dashboard(db, company)
    item = dash["promises"][0]
    assert item["due_state"] == "overdue_unverified" and item["checks"] == []
