"""Frontera confiable del document_quote. SINTETICO, sin red ni BD."""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from app.services.commitment_followup_service import FollowupCriterion, FollowupEvidence, evaluate_followup
from app.services.commitment_primary_bridge import evidence_from_pipeline
from app.services.commitment_primary_pipeline import PipelineResult, quote_for_fact
from app.services.followup_primary_evidence_adapter import ReportedObservation
from tests.test_commitment_primary_pipeline import (
    TODAY,
    URL,
    _doc,
    _synthetic_reported_rule,  # noqa: F401
)

PERIOD_END = date(2026, 6, 30)


@dataclass
class Fact:
    id: int = 7
    metric: str = "synthetic_reported_growth"
    value: Decimal = Decimal("22")
    unit: str = "%"
    period: str = "2026-06-30:Q2"
    fiscal_year: int | None = 2026
    fiscal_quarter: str | None = "Q2"
    is_reported: bool = True
    is_adjusted: bool = False
    accession_number: str | None = "0000000000-26-000002"


@dataclass
class Doc:
    id: int = 3
    source_url: str = URL


def _criterion(operator=">=", target="20", **kw):
    base = dict(
        tenant_id=1, company_id=1, promise_id=5, metric="synthetic_reported_growth",
        operator=operator, target=Decimal(target), unit="%", period="Q2 2026",
        period_end=PERIOD_END, promised_on=date(2026, 2, 1), due_on=date(2026, 7, 31),
        basis="declared_structured",
    )
    base.update(kw)
    return FollowupCriterion(**base)


def _out(fact=None, doc=None):
    document = doc or _doc()
    f = fact or Fact()
    obs = ReportedObservation(1, 1, f.id, f.metric, f.value, f.unit, URL, document.asset.period, True, False)
    return quote_for_fact(tenant_id=1, company_id=1, document=document, fact=obs, today=TODAY)


def _ev(out=None, fact=None, source=None):
    return evidence_from_pipeline(
        out or _out(fact), tenant_id=1, company_id=1, fact=fact or Fact(),
        source_document=source or Doc(), fiscal_end_month="12")


def test_real_quote_passes_with_traceability():
    ev = _ev()
    assert ev is not None and ev.page == 3
    res = evaluate_followup(_criterion(), (ev,), today=TODAY)
    assert (res.status, res.basis, res.reason_code) == (
        "fulfilled", "automatic_document_quote", "criterion_matched")
    assert res.suggestion_only and res.provenance == "system_checked"
    assert evaluate_followup(_criterion(target="25"), (ev,), today=TODAY).status == "missed"


def test_engine_rejects_hand_built_document_quote_even_with_flags_hashes_and_numeric_match():
    """Repros del auditor: guidance y cifra suelta con rastro y flags a mano -> sin veredicto."""
    for text in ("We expect growth of 22% next year.", "Our 22 offices grew.",
                 "Synthetic growth was 22% year-on-year reported in U.S. dollars."):
        forged = FollowupEvidence(
            tenant_id=1, company_id=1, fact_id=7, document_id=3, chunk_id=0,
            metric="synthetic_reported_growth", value=Decimal("22"), unit="%", period="Q2 2026",
            period_end=PERIOD_END, published_on=date(2026, 8, 5), source_url=URL, excerpt=text,
            reported=True, adjusted=False, primary_source_verified=True, quote_verified=True,
            checked_at=TODAY, quote_kind="document_quote", page=3, char_start=0,
            char_end=len(text), text_sha256="a" * 64, bytes_sha256="b" * 64, extractor="pypdf==6")
        res = evaluate_followup(_criterion(), (forged,), today=TODAY)
        assert (res.status, res.reason_code) == ("insufficient_evidence", "invalid_quote")


def test_boundary_rejects_forged_or_mismatched_inputs():
    out = _out()
    assert evidence_from_pipeline(
        PipelineResult(result=out.result, document=out.document), tenant_id=1, company_id=1,
        fact=Fact(), source_document=Doc()) is None
    for kw in (
        dict(fact=Fact(value=Decimal("23"))), dict(fact=Fact(is_adjusted=True)),
        dict(fact=Fact(is_reported=False)), dict(fact=Fact(fiscal_year=None)),
        dict(fact=Fact(fiscal_quarter="FY")), dict(fact=Fact(period="Q2 2026")),
        dict(fact=Fact(period="2026-13-40")), dict(source=Doc(source_url=URL + "?x=1")),
        dict(source=None),
    ):
        fact = kw.get("fact", Fact())
        source = kw.get("source", Doc()) if "source" in kw else Doc()
        got = evidence_from_pipeline(out, tenant_id=1, company_id=1, fact=fact,
                                     source_document=source)
        assert got is None, kw
    tampered = replace(out.document, text=out.document.text.replace("22%", "25%"))
    assert evidence_from_pipeline(
        replace(out, document=tampered, _seal=out._seal), tenant_id=1, company_id=1,
        fact=Fact(), source_document=Doc()) is None


def test_no_evidence_from_pipeline_when_value_not_in_original():
    out = _out(fact=Fact(value=Decimal("99")))
    assert out.result.evidence is None
    assert evidence_from_pipeline(out, tenant_id=1, company_id=1, fact=Fact(value=Decimal("99")),
                                  source_document=Doc()) is None


def test_fact_period_must_be_anchored_and_reproduce_quarter():
    """SINTETICO: corte libre/discordante, sin accession o sin mes fiscal anclado -> sin evidencia."""
    for bad in ("2020-03-31:Q2", "2026-06-30:Q4", "2026-06-30", "2026-06-30:FY", "2028-06-30:Q2",
                "2026-12-31:Q2"):  # diciembre con cierre fiscal dic es Q4, no Q2
        assert _ev(out=_out(Fact()), fact=Fact(period=bad)) is None, bad
    assert _ev(out=_out(Fact()), fact=Fact(accession_number=None)) is None
    assert _ev(out=_out(Fact()), fact=Fact(accession_number="x")) is None
    f = Fact()
    assert evidence_from_pipeline(
        _out(f), tenant_id=1, company_id=1, fact=f, source_document=Doc()) is None  # sin mes fiscal
    assert _ev(out=_out(Fact()), fact=Fact()) is not None
