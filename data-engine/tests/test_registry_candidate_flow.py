"""Flujo extraer -> candidato -> revision humana. Textos SINTETICOS (no son transcripciones reales)."""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.commitment_extraction_service import extract_candidates
from app.services.commitment_tracking_service import CommitmentTrackingError, CommitmentTrackingService

# SINTETICO: imita el formato en bloques (nombre / cargo / texto) de transcripciones PDF.
SYN = (
    "Operator: Welcome.\n"
    "Jane Roe \nChief Executive Officer, Acme Corp. \n"
    "The number of sites we are live in matters. So to remind you, we're live in 7 sites, and we're on track "
    "to be live in 15 sites by year-end. We will add 3 regions in 2028. \n"
    " ..................................................... \n"
    "Operator: First question.\n"
    "Sam Poe \nAnalyst, Big Bank Capital, Inc. \n"
    "Do you expect to be on track to be live in 99 sites by year-end? Will we see 5 more by the end of the year?\n"
    "Jane Roe \nChief Executive Officer, Acme Corp. \nNo comment.\n"
)


def test_block_format_extracts_management_only_with_inferred_year_end_and_support_quote():
    cs = extract_candidates(SYN, call_date=date(2026, 8, 5))
    assert [c.quote_literal for c in cs][0].endswith("15 sites by year-end.")
    c = cs[0]
    assert c.speaker == "Jane Roe" and c.parser == "bloques_pdf"
    assert c.due_date_hint == date(2026, 12, 31) and c.due_basis == "year_end_inferred_from_call_year"
    assert "due_year_inferred" in c.flags and c.support_quote.startswith("The number of sites")
    assert all("99 sites" not in x.quote_literal and "5 more" not in x.quote_literal for x in cs)


def test_year_end_without_call_date_gives_no_due_date():
    c = extract_candidates(SYN)[0]
    assert c.due_date_hint is None and c.due_basis == "none"


def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    db = Session(eng)
    db.info["tenant_id"] = None
    co = Company(ticker="ACME", name="ACME", exchange="NYSE", currency="USD", sector="S", industry="I",
                 company_type="holding", valuation_model="unassigned",
                 special_sources=[], special_risks=[], factor_tags=[])
    db.add(co)
    db.commit()
    return db, co


def test_registry_route_creates_unreviewed_candidates_then_human_review(monkeypatch):
    from app.api.routes import companies as routes

    db, co = _db()
    doc = SimpleNamespace(text=SYN, url="https://x.invalid/t.pdf",
                          asset=SimpleNamespace(published_on=date(2026, 8, 5)))
    monkeypatch.setattr("app.services.commitment_primary_pipeline.fetch_registered_document_isolated",
                        lambda t, u, today: (doc, {}))
    monkeypatch.setattr("app.services.transcript_source_service.throttle", lambda k: True)
    monkeypatch.setattr(routes, "resolve_company", lambda db_, t: co)
    out = routes.extract_management_candidates_from_registry(
        "ACME", routes.ManagementCandidateFromRegistry(source_url="https://x.invalid/t.pdf"), db=db, principal=None)
    first = out[0]
    assert first["status"] == "candidate" and first["source_check"] == "registro_oficial_exacto"
    assert first["due_basis"] == "year_end_inferred_from_call_year" and first["support_quote"]
    assert first["date_basis"] == "call_date" and first["fulfillment_criteria"] is None
    row = db.get(routes.ManagementPromise, first["id"])
    svc = CommitmentTrackingService()
    with pytest.raises(CommitmentTrackingError):  # sin revisar no hay veredicto
        svc.add_check(db, row, outcome="met", checked_on=date(2027, 1, 5),
                      evidence_url="https://x.invalid/e", evidence_excerpt="x")
    reviewed = svc.review_candidate(db, row, fulfillment_criteria="15 sitios live segun documento oficial",
                                    due_date=date(2026, 12, 31), confirmed_source_checked=True, user_id="u1")
    assert reviewed.status == "open" and reviewed.metadata_["review_kind"] == "user_declared"


def test_registry_route_rejects_unregistered_url(monkeypatch):
    from fastapi import HTTPException

    from app.api.routes import companies as routes

    db, co = _db()
    monkeypatch.setattr("app.services.transcript_source_service.throttle", lambda k: True)
    monkeypatch.setattr(routes, "resolve_company", lambda db_, t: co)
    with pytest.raises(HTTPException) as e:
        routes.extract_management_candidates_from_registry(
            "ACME", routes.ManagementCandidateFromRegistry(source_url="https://evil.invalid/t.pdf"),
            db=db, principal=None)
    assert e.value.status_code == 422
