"""KPIExtractionService approval + normalization contract tests.

KPI candidates only become facts through human approval: value
normalization must be exact, contradictions must leave a revision trail,
and approved observations must be immutable to rejection.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    CompanyKPI,
    Document,
    DocumentChunk,
    FactRevision,
    FinancialFact,
    KPIExtractionCandidate,
)
from app.services.kpi_extraction_service import KPIExtractionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _scaffold(db: Session, *, status: str = "pending_approval", ticker: str = "AAPL") -> KPIExtractionCandidate:
    company = Company(
        ticker=ticker, name="Apple", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    kpi = CompanyKPI(company_id=company.id, metric_key="revenue", display_name="Revenue")
    document = Document(
        company_id=company.id, title="10-K 2025", source_type="SEC",
        published_at=datetime.now(UTC), metadata_={},
    )
    db.add_all([kpi, document])
    db.flush()
    chunk = DocumentChunk(document_id=document.id, chunk_index=0, text="Revenue was 391 billion")
    db.add(chunk)
    db.flush()
    candidate = KPIExtractionCandidate(
        company_id=company.id, company_kpi_id=kpi.id, document_id=document.id,
        document_chunk_id=chunk.id, metric_key="revenue", raw_label="Revenue",
        raw_value="391", raw_unit="billion", normalized_value=Decimal("391000000000"),
        canonical_unit="USD", period="2025-09-27:FY", fiscal_year=2025,
        status=status, confidence=Decimal("0.9"),
    )
    db.add(candidate)
    db.commit()
    return candidate


def test_approve_creates_canonical_fact_from_candidate(db):
    candidate = _scaffold(db)
    fact = KPIExtractionService().approve(db, candidate, actor="analyst")

    assert fact.metric == "revenue"
    assert fact.value == Decimal("391000000000")
    assert fact.source_type == "SEC"
    assert fact.is_reported is True
    assert candidate.status == "approved"
    assert candidate.approved_by == "analyst"
    assert candidate.canonical_fact_id == fact.id
    assert db.scalar(select(FactRevision)) is None  # no contradiction: no revision


def test_approve_contradiction_records_revision_trail(db):
    candidate = _scaffold(db)
    existing = FinancialFact(
        company_id=candidate.company_id, metric="revenue",
        value=Decimal("380000000000"), unit="USD", period="2025-09-27:FY",
        source_type="SEC", is_reported=True, confidence=Decimal("0.8"),
    )
    db.add(existing)
    db.commit()

    fact = KPIExtractionService().approve(db, candidate, actor="analyst")
    assert fact.id == existing.id
    assert fact.value == Decimal("391000000000")  # canonical value updated
    revision = db.scalar(select(FactRevision))
    assert revision is not None
    assert revision.previous_value == Decimal("380000000000")
    assert revision.new_value == Decimal("391000000000")
    assert revision.approved_by == "analyst"
    assert revision.canonical_version == 1
    assert revision.status == "approved"


def test_approve_rejects_unreconciled_or_missing_document(db):
    candidate = _scaffold(db, status="rejected")
    with pytest.raises(ValueError, match="pending candidates"):
        KPIExtractionService().approve(db, candidate, actor="analyst")


def test_reject_marks_candidate_but_never_approved_ones(db):
    candidate = _scaffold(db)
    KPIExtractionService.reject(db, candidate, actor="analyst")
    assert candidate.status == "rejected"
    assert candidate.approved_by == "analyst"

    approved = _scaffold(db, ticker="MSFT")
    # _scaffold rows are unique by raw_value; distinguish this one.
    approved.raw_value = "392"
    approved.status = "approved"
    db.commit()
    with pytest.raises(ValueError, match="cannot be rejected"):
        KPIExtractionService.reject(db, approved, actor="analyst")


def test_normalize_units_negatives_and_percents():
    normalize = KPIExtractionService._normalize
    value, meta = normalize("391", "billion USD", "USD")
    assert value == Decimal("391000000000")
    assert meta["status"] == "normalized"
    value, _ = normalize("2.5", "million", "USD")
    assert value == Decimal("2500000")
    value, _ = normalize("(1,250)", "thousand", "USD")
    assert value == Decimal("-1250000")
    value, meta = normalize("25", "%", "decimal")
    assert value == Decimal("0.25")
    assert meta["percent_to_decimal"] is True
    value, meta = normalize("not-a-number", "USD", "USD")
    assert value is None
    assert meta["status"] == "invalid_number"


def test_existing_approved_candidates_return_before_any_llm(db):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    existing = _scaffold(db, status="approved")
    original = existing.normalized_value
    provider = SimpleNamespace(complete=AsyncMock(side_effect=AssertionError("LLM called")))
    result = asyncio.run(KPIExtractionService(provider).extract_document(db, db.get(Document, existing.document_id)))
    assert result == [existing]
    assert existing.normalized_value == original and existing.status == "approved"
    provider.complete.assert_not_awaited()
