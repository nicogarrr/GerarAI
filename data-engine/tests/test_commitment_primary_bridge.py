"""Consumo de document_quote por el motor. SINTETICO, sin red ni BD."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.services.commitment_followup_service import FollowupCriterion, evaluate_followup
from app.services.commitment_primary_bridge import evidence_from_pipeline
from app.services.commitment_primary_pipeline import quote_for_fact
from app.services.followup_primary_evidence_adapter import ReportedObservation
from tests.test_commitment_primary_pipeline import TODAY, URL, _doc

PERIOD_END = date(2026, 6, 30)


def _criterion(operator=">=", target="20", **kw):
    base = dict(
        tenant_id=1, company_id=1, promise_id=5, metric="gross_bookings_growth_yoy",
        operator=operator, target=Decimal(target), unit="%", period="Q2 2026",
        period_end=PERIOD_END, promised_on=date(2026, 2, 1), due_on=date(2026, 7, 31),
        basis="declared_structured",
    )
    base.update(kw)
    return FollowupCriterion(**base)


def _evidence(value="22"):
    doc = _doc()
    fact = ReportedObservation(1, 1, 7, "gross_bookings_growth_yoy", Decimal(value), "%", URL,
                               doc.asset.period, True, False)
    out = quote_for_fact(tenant_id=1, company_id=1, document=doc, fact=fact, today=TODAY)
    return evidence_from_pipeline(out, document_id=3, chunk_id=0, fact_period="2026-06-30:Q2")


def test_document_quote_is_consumed_with_visible_traceability():
    ev = _evidence()
    assert ev is not None and ev.quote_kind == "document_quote" and ev.page == 3
    res = evaluate_followup(_criterion(), (ev,), today=TODAY)
    assert (res.status, res.basis, res.reason_code) == (
        "fulfilled", "automatic_document_quote", "criterion_matched")
    assert res.suggestion_only and res.provenance == "system_checked"


def test_exact_operator_no_tolerance():
    res = evaluate_followup(_criterion(target="25"), (_evidence(),), today=TODAY)
    assert (res.status, res.basis) == ("missed", "automatic_document_quote")


def test_incomplete_or_inconsistent_trace_is_invalid_quote():
    ev = _evidence()
    for bad in (
        replace(ev, text_sha256=None), replace(ev, bytes_sha256="zz"), replace(ev, extractor=None),
        replace(ev, page=0), replace(ev, char_end=ev.char_end + 1),
        replace(ev, excerpt=ev.excerpt.replace("22%", "23%"), char_end=ev.char_end),
    ):
        res = evaluate_followup(_criterion(), (bad,), today=TODAY)
        assert (res.status, res.reason_code) == ("insufficient_evidence", "invalid_quote")


def test_period_mismatch_and_not_due_do_not_decide():
    ev = _evidence()
    assert evaluate_followup(_criterion(period="Q3 2026"), (ev,), today=TODAY).reason_code in {
        "period_mismatch", "invalid_dates"}
    assert evaluate_followup(_criterion(due_on=date(2026, 12, 31)), (ev,), today=TODAY
                             ).status == "pending"


def test_bridge_refuses_without_evidence():
    doc = _doc()
    fact = ReportedObservation(1, 1, 7, "gross_bookings_growth_yoy", Decimal("99"), "%", URL,
                               doc.asset.period, True, False)
    out = quote_for_fact(tenant_id=1, company_id=1, document=doc, fact=fact, today=TODAY)
    assert evidence_from_pipeline(out, document_id=3, chunk_id=0, fact_period="2026-06-30:Q2") is None


def test_bridge_rejects_hand_built_result_and_missing_fact_cutoff():
    from app.services.commitment_primary_pipeline import PipelineResult

    doc = _doc()
    fact = ReportedObservation(1, 1, 7, "gross_bookings_growth_yoy", Decimal("22"), "%", URL,
                               doc.asset.period, True, False)
    out = quote_for_fact(tenant_id=1, company_id=1, document=doc, fact=fact, today=TODAY)
    forged = PipelineResult(result=out.result, document=out.document)
    assert evidence_from_pipeline(forged, document_id=3, chunk_id=0,
                                  fact_period="2026-06-30:Q2") is None
    for bad in (None, "Q2 2026", "2026-13-40"):
        assert evidence_from_pipeline(out, document_id=3, chunk_id=0, fact_period=bad) is None
