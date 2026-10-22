"""ManagementCredibilityService reconciliation contracts.

A credibility score is only meaningful if promise matching is strict: an
annual promise must never be reconciled against a quarterly observation,
there is no invented tolerance (a miss is "missed", never "partial"), a fact
without a traceable source document is ignored, and unmatched promises stay
honestly open.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.management_credibility_service import ManagementCredibilityService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="MCO", name="MCO", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _doc(db, company):
    doc = Document(
        company_id=company.id, title="10-Q", source_type="filing",
        source_url="https://www.sec.gov/Archives/example-10q",
        published_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    db.add(doc)
    db.flush()
    return doc.id


def _period(year, quarter):
    ends = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31", "FY": "12-31"}
    return f"{year}-{ends[quarter]}:{quarter}"


def _fact(
    db, company, value, year=2025, quarter="FY", metric="revenue", with_source=True,
    published=datetime(2026, 3, 1, tzinfo=UTC), adjusted=False,
):
    doc_id = None
    if with_source:
        doc = Document(
            company_id=company.id, title="10-K", source_type="filing",
            source_url="https://www.sec.gov/Archives/example",
            published_at=published,
        )
        db.add(doc)
        db.flush()
        doc_id = doc.id
    fact = FinancialFact(
        source_id=doc_id,
        company_id=company.id, metric=metric, value=Decimal(str(value)),
        unit="USD", period=_period(year, quarter),
        fiscal_year=year, fiscal_quarter=None if quarter == "FY" else quarter,
        source_type="filing", is_adjusted=adjusted,
    )
    db.add(fact)
    db.commit()
    return fact


def _mark_reviewed(db, promise):
    """Criterio estructurado revisado por una persona (provenance user_declared)."""
    promise.metadata_ = {
        **(promise.metadata_ or {}),
        "reviewed_at": "2026-10-22T12:00:00+00:00",
        "review_kind": "user_declared",
    }
    db.commit()
    return promise


def _promise(db, company, *, period="FY2025", operator=">=", target="100", reviewed=True):
    promise = _promise_raw(db, company, period=period, operator=operator, target=target)
    return _mark_reviewed(db, promise) if reviewed else promise


def _promise_raw(db, company, *, period="FY2025", operator=">=", target="100"):
    return ManagementCredibilityService().register(
        db, company,
        promise=f"Revenue {operator} {target} in {period}",
        promise_date=date(2024, 2, 1), expected_period=period,
        metric="revenue", operator=operator,
        target_value=Decimal(target), unit="USD",
    )


def test_met_when_operator_satisfied(db):
    c = _company(db)
    _fact(db, c, 120)
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "met"
    assert p.actual_value == Decimal("120")


def test_missed_when_clearly_below_target(db):
    c = _company(db)
    _fact(db, c, 80)
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "missed"


def test_no_invented_tolerance_close_miss_is_missed_not_partial(db):
    c = _company(db)
    _fact(db, c, 97)  # 3% below target: no tolerance rule, exact comparison only
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "missed"


def test_clear_miss_is_missed(db):
    c = _company(db)
    _fact(db, c, 94)  # 6% below target
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "missed"


def test_annual_promise_ignores_quarterly_fact(db):
    c = _company(db)
    _fact(db, c, 130, quarter="Q3")  # same fiscal year, but quarterly
    _promise(db, c, period="FY2025")
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_fact_id is None


def test_quarterly_promise_matches_quarterly_fact(db):
    c = _company(db)
    _fact(db, c, 130, quarter="Q2")
    _promise(db, c, period="Q2 2025")
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "met"


def test_quarterly_promise_does_not_infer_fiscal_year_from_calendar_for_null_fiscal_year(db):
    """Hechos de la ingesta 10-Q: fiscal_year NULL, period '<end>:Qn'."""
    c = _company(db)
    fact = FinancialFact(
        source_id=_doc(db, c),
        company_id=c.id, metric="revenue", value=Decimal("130"),
        unit="USD", period="2025-06-30:Q2",
        fiscal_year=None, fiscal_quarter="Q2",
        source_type="filing",
    )
    db.add(fact)
    db.commit()
    _promise(db, c, period="2025 Q2")
    [p] = ManagementCredibilityService().reconcile(db, c)
    # año fiscal no explicito: no se infiere desde el calendario -> sin hecho ni veredicto
    assert p.status == "open"
    assert p.actual_fact_id is None


def test_quarterly_promise_ignores_null_fiscal_year_fact_from_other_year(db):
    c = _company(db)
    fact = FinancialFact(
        source_id=_doc(db, c),
        company_id=c.id, metric="revenue", value=Decimal("130"),
        unit="USD", period="2024-06-30:Q2",
        fiscal_year=None, fiscal_quarter="Q2",
        source_type="filing",
    )
    db.add(fact)
    db.commit()
    _promise(db, c, period="2025 Q2")
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_fact_id is None


def test_unmatched_promise_stays_open(db):
    c = _company(db)
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_value is None


def test_numeric_promise_requires_supported_operator(db):
    c = _company(db)
    with pytest.raises(ValueError):
        _promise(db, c, operator="~=")


def test_promise_without_target_records_outcome(db):
    c = _company(db)
    _fact(db, c, 110)
    ManagementCredibilityService().register(
        db, c, promise="Revenue will grow in FY2025",
        promise_date=date(2024, 2, 1), expected_period="FY2025",
        metric="revenue", operator=None, target_value=None, unit=None,
    )
    [p] = ManagementCredibilityService().reconcile(db, c)
    # sin criterio estructurado no hay veredicto; el hecho queda solo como contexto
    assert p.status == "open"
    assert p.actual_value == Decimal("110")
    assert p.evidence[-1]["context_only"] is True


# --- Procedencia verificable (0078) -----------------------------------------


def _claim(db, company, text):
    from app.models.entities import CallClaim, Transcript

    transcript = Transcript(
        company_id=company.id, title="Q4 call (sintetico)", period="Q4 2025",
        transcript_text=text,
    )
    db.add(transcript)
    db.commit()
    claim = CallClaim(
        transcript_id=transcript.id, speaker="Persona Sintetica", speaker_role="CFO",
        claim=text, claim_type="commitment", period="FY2025",
    )
    db.add(claim)
    db.commit()
    return claim


def test_import_does_not_turn_a_year_into_a_numeric_target(db):
    """«25 satelites en 2025»: la heuristica tomaba un numero del texto como
    objetivo y la conciliacion lo daba por promesa numerica autenticada."""
    company = _company(db)
    _claim(db, company, "In 2025 we will have 25 satellites in orbit")
    rows = ManagementCredibilityService().import_call_claims(db, company)
    assert len(rows) == 1
    row = rows[0]
    assert row.operator is None and row.target_value is None
    assert row.metadata_["suggested_target_unverified"] is not None  # sugerencia, no dato
    assert row.status == "open"


def test_import_marks_date_basis_registered_not_call_date(db):
    company = _company(db)
    _claim(db, company, "We expect to launch the new product by year end")
    row = ManagementCredibilityService().import_call_claims(db, company)[0]
    assert row.date_basis == "registered_at"
    assert row.call_date is None
    assert row.quote_literal == "We expect to launch the new product by year end"
    assert row.speaker == "Persona Sintetica" and row.speaker_role == "CFO"


def test_register_records_provenance_and_date_basis(db):
    company = _company(db)
    svc = ManagementCredibilityService()
    row = svc.register(
        db, company, promise="Ampliar la oferta antes de fin de ano",
        promise_date=date(2026, 5, 11), expected_period="FY2026", metric=None,
        operator=None, target_value=None, unit=None,
        quote_literal="[...] into more complex offerings", speaker="X", speaker_role="CFO",
        call_date=date(2026, 5, 11), source_url="https://example.invalid/t.pdf",
        transcript_locator="27:04", due_date=date(2026, 12, 31),
        fulfillment_criteria="Oferta disponible al publico",
    )
    payload = ManagementCredibilityService.payload(row)
    assert payload["date_basis"] == "call_date"
    assert payload["due_date"] == date(2026, 12, 31)
    assert payload["fulfillment_criteria"] == "Oferta disponible al publico"
    other = svc.register(
        db, company, promise="Otra", promise_date=date(2026, 5, 12), expected_period="FY2026",
        metric=None, operator=None, target_value=None, unit=None,
    )
    assert other.date_basis == "user_entered" and other.quote_literal is None


SYNTH_CALL = """Acme Corp (ACME)
Second Quarter 2030 Results Conference Call

Ana Perez, CEO

We expect to launch 12 units by the end of 2031. We love our customers.
"""


def test_extracted_candidates_are_suggested_never_reconciled_and_deduped(db):
    company = _company(db)
    service = ManagementCredibilityService()
    rows = service.register_extracted_candidates(
        db, company, transcript_text=SYNTH_CALL, call_date=date(2030, 7, 1),
        source_url="https://example.invalid/synthetic",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "candidate" and row.operator is None and row.target_value is None
    assert row.metadata_["source_status"] == "suggested"
    assert row.transcript_locator.startswith("ws_collapse_v1:")
    assert row.due_date == date(2031, 12, 31) and row.date_basis == "user_entered"
    assert len(row.metadata_["context_before"]) <= 80 and len(row.metadata_["context_after"]) <= 80
    assert "Second Quarter 2030 Results Conference Call" not in row.promise
    service.reconcile(db, company)
    db.refresh(row)
    assert row.status == "candidate"
    again = service.register_extracted_candidates(
        db, company, transcript_text=SYNTH_CALL, call_date=date(2030, 7, 1),
        source_url="https://example.invalid/synthetic",
    )
    assert again == []
    dash = service.dashboard(db, company)
    assert dash["counts"]["candidate"] == 1 and dash["score"] is None


def test_legacy_heuristic_promises_are_excluded_from_score(db):
    from app.models.entities import ManagementPromise

    company = _company(db)
    db.add(ManagementPromise(
        company_id=company.id, promise="In 2025 we will have 25 satellites",
        promise_date=date(2025, 1, 1), expected_period="2025", metric="revenue",
        operator=">=", target_value=Decimal("2025"), status="missed",
        metadata_={"source": "call_claim"}, evidence=[],
    ))
    db.commit()
    dash = ManagementCredibilityService().dashboard(db, company)
    assert dash["score"] is None and dash["grade"] == "insufficient_history"
    assert dash["legacy_excluded_from_score"] == 1
    assert dash["promises"][0]["legacy_heuristic_target"] is True


def test_same_quote_in_other_call_is_not_a_duplicate_and_cap_applies(db, monkeypatch):
    from app.services import management_credibility_service as mod

    company = _company(db)
    service = ManagementCredibilityService()
    a = service.register_extracted_candidates(
        db, company, transcript_text=SYNTH_CALL, call_date=date(2030, 7, 1),
        source_url="https://example.invalid/a",
    )
    b = service.register_extracted_candidates(
        db, company, transcript_text=SYNTH_CALL, call_date=date(2030, 10, 1),
        source_url="https://example.invalid/b",
    )
    assert len(a) == 1 and len(b) == 1
    dash = service.dashboard(db, company)
    assert dash["counts"]["total"] == 2 and dash["counts"]["registered"] == 0
    monkeypatch.setattr(mod, "MAX_CANDIDATES_PER_COMPANY", 2)
    with pytest.raises(ValueError, match="Limite"):
        service.register_extracted_candidates(
            db, company, transcript_text=SYNTH_CALL, call_date=date(2031, 1, 1),
            source_url="https://example.invalid/c",
        )


def test_candidates_are_tenant_scoped():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as a:
        a.info["tenant_id"] = 1
        company = _company(a)
        ManagementCredibilityService().register_extracted_candidates(
            a, company, transcript_text=SYNTH_CALL, call_date=date(2030, 7, 1),
            source_url="https://example.invalid/a",
        )
        cid = company.id
    with Session(engine) as b:
        b.info["tenant_id"] = 2
        from sqlalchemy import select

        from app.models.entities import ManagementPromise

        rows = b.scalars(select(ManagementPromise).where(ManagementPromise.company_id == cid)).all()
        assert rows == []



def test_portfolio_commitments_only_for_held_companies(db):
    from app.api.routes.portfolio import management_commitments
    from app.models.entities import Position

    held = _company(db)
    other = Company(
        ticker="OTH", name="OTH", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(other)
    db.commit()
    db.add(Position(company_id=held.id, quantity=Decimal("3"), as_of=date(2030, 1, 1)))
    db.commit()
    service = ManagementCredibilityService()
    for company in (held, other):
        service.register_extracted_candidates(
            db, company, transcript_text=SYNTH_CALL, call_date=date(2030, 7, 1),
            source_url="https://example.invalid/a",
        )
    data = management_commitments(db)
    assert data["held_count"] == 1
    assert [c["ticker"] for c in data["companies"]] == ["MCO"]
    assert data["companies"][0]["counts"] == {"total": 1, "candidate": 1, "registered": 0}
    assert data["companies"][0]["items"][0]["source_status"] == "suggested"


def test_manual_promise_with_user_target_is_not_excluded_from_score(db):
    company = _company(db)
    service = ManagementCredibilityService()
    _fact(db, company, 120, year=2025)
    promise = service.register(
        db, company, promise="Revenue above 100", promise_date=date(2024, 1, 1),
        expected_period="FY2025", metric="revenue", operator=">=",
        target_value=Decimal("100"), unit="USD",
    )
    _mark_reviewed(db, promise)
    service.reconcile(db, company)
    dash = service.dashboard(db, company)
    assert dash["legacy_excluded_from_score"] == 0
    assert dash["promises"][0]["legacy_heuristic_target"] is False
    assert dash["score"] == 1


def test_portfolio_commitments_aggregates_net_position_without_duplicates(db):
    from app.api.routes.portfolio import management_commitments
    from app.models.entities import Position

    held = _company(db)
    db.add_all([
        Position(company_id=held.id, quantity=Decimal("3"), as_of=date(2030, 1, 1)),
        Position(company_id=held.id, quantity=Decimal("2"), as_of=date(2030, 1, 1)),
    ])
    db.commit()
    data = management_commitments(db)
    assert data["held_count"] == 1 and [c["ticker"] for c in data["companies"]] == ["MCO"]
    db.add(Position(company_id=held.id, quantity=Decimal("-5"), as_of=date(2030, 1, 1)))
    db.commit()
    assert management_commitments(db)["held_count"] == 0  # neta 0: no en cartera


def test_reconcile_ignores_unreported_and_other_unit_facts(db):
    c = _company(db)
    estimated = _fact(db, c, 500)
    estimated.is_reported = False
    other_unit = _fact(db, c, 900)
    other_unit.unit = "EUR"
    db.commit()
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_fact_id is None


def test_reconcile_uses_reported_fact_with_same_unit_case_insensitive(db):
    c = _company(db)
    ignored = _fact(db, c, 500)
    ignored.is_reported = False
    ok = _fact(db, c, 120, year=2025)
    ok.unit = "usd"
    db.commit()
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "met"
    assert p.actual_fact_id == ok.id


def test_fact_without_traceable_source_document_is_ignored(db):
    c = _company(db)
    _fact(db, c, 500, with_source=False)
    _promise(db, c)
    [p] = ManagementCredibilityService().reconcile(db, c)
    assert p.status == "open"
    assert p.actual_fact_id is None


def test_unreviewed_promise_gets_context_but_no_verdict_and_keeps_prior_status(db):
    c = _company(db)
    _fact(db, c, 120)
    p = _promise(db, c, reviewed=False)
    ManagementCredibilityService().reconcile(db, c)
    db.refresh(p)
    assert p.status == "open"
    assert p.actual_value == Decimal("120")
    assert p.evidence[-1]["context_only"] is True
    # un juicio previo no se sobrescribe sin criterio revisado
    p.status = "partial"
    db.commit()
    ManagementCredibilityService().reconcile(db, c)
    db.refresh(p)
    assert p.status == "partial"


def test_reviewed_promise_gets_exact_verdict_with_source(db):
    c = _company(db)
    fact = _fact(db, c, 120)
    p = _promise(db, c)
    ManagementCredibilityService().reconcile(db, c)
    db.refresh(p)
    assert p.status == "met"
    assert p.evidence[-1]["context_only"] is False
    assert p.evidence[-1]["source_document_id"] == fact.source_id


def _reconciled(db, c, p):
    ManagementCredibilityService().reconcile(db, c)
    db.refresh(p)
    return p


def test_year_only_or_half_year_period_never_matches_a_quarter_fact(db):
    c = _company(db)
    _fact(db, c, 90, year=2026, quarter="Q2")
    for period in ("2026", "H1 2026", "primer semestre 2026"):
        p = _promise(db, c, period=period)
        assert _reconciled(db, c, p).status == "open"
        assert p.actual_value is None
        assert not p.evidence


def test_adjusted_fact_is_not_used(db):
    c = _company(db)
    _fact(db, c, 120, adjusted=True)
    p = _promise(db, c)
    assert _reconciled(db, c, p).status == "open"
    assert p.actual_value is None


def test_open_period_gives_context_not_verdict(db):
    c = _company(db)
    _fact(db, c, 120, year=2026, quarter="Q4", published=datetime(2026, 3, 1, tzinfo=UTC))
    p = _promise(db, c, period="Q4 2026")
    assert _reconciled(db, c, p).status == "open"
    assert p.evidence[-1]["context_only"] is True


def test_document_not_after_promise_gives_context_not_verdict(db):
    c = _company(db)
    _fact(db, c, 120, published=datetime(2024, 1, 1, tzinfo=UTC))
    p = _promise(db, c)
    assert _reconciled(db, c, p).status == "open"
    assert p.evidence[-1]["context_only"] is True


def test_conflicting_values_for_same_period_abstain(db):
    c = _company(db)
    _fact(db, c, 120)
    _fact(db, c, 80)
    p = _promise(db, c)
    assert _reconciled(db, c, p).status == "open"
    assert p.actual_value is None


def test_reconcile_is_idempotent_and_evidence_dedups(db):
    c = _company(db)
    _fact(db, c, 120)
    p = _promise(db, c)
    for _ in range(5):
        _reconciled(db, c, p)
    assert len(p.evidence) == 1
    assert p.status == "met"


def test_fy_promise_ignores_unmarked_non_annual_cutoff(db):
    c = _company(db)
    f = _fact(db, c, 90)
    f.period = "2025-09-30"
    f.fiscal_quarter = None
    db.commit()
    p = _promise(db, c)
    assert _reconciled(db, c, p).status == "open"
    assert p.actual_value is None


def test_fiscal_quarter_not_matched_by_calendar_year(db):
    c = _company(db)
    f = _fact(db, c, 90, year=2026, quarter="Q1")  # Q1 del año fiscal 2026
    f.period = "2025-12-31:Q1"
    db.commit()
    p = _promise(db, c, period="Q1 2025")
    assert _reconciled(db, c, p).status == "open"
    assert p.actual_value is None


def test_fact_without_authentic_cutoff_date_gives_context_only(db):
    c = _company(db)
    f = _fact(db, c, 120)
    f.period = "FY2025"
    db.commit()
    p = _promise(db, c)
    assert _reconciled(db, c, p).status == "open"
    assert p.evidence[-1]["context_only"] is True
