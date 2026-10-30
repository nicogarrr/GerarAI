from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document
from app.services.earnings_service import EarningsWorkflowService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db, title, metadata=None):
    company = db.query(Company).first()
    if company is None:
        company = Company(ticker="TEST", name="Test", exchange="NASDAQ", company_type="operating", valuation_model="dcf")
        db.add(company)
        db.flush()
    doc = Document(company_id=company.id, title=title, source_type="earnings_release",
                   metadata_=metadata or {}, published_at=datetime(2026, 10, 1, tzinfo=UTC))
    db.add(doc)
    db.commit()
    return company, doc


def test_automatic_selection_requires_both_quarter_and_year(db):
    company, expected = seed(db, "Q2 2026 results")
    seed(db, "Q1 2026 results")
    seed(db, "Q2 2025 results")
    seed(db, "Q2 20260 typo")
    docs = EarningsWorkflowService()._documents(db, company, 2026, "Q2", [])
    assert [doc.id for doc in docs] == [expected.id]


def test_no_matching_period_fails_instead_of_using_recent_documents(db):
    company, _ = seed(db, "Q1 2026 results")
    with pytest.raises(ValueError, match="period"):
        EarningsWorkflowService()._documents(db, company, 2026, "Q2", [])


def test_structured_period_is_usable(db):
    company, expected = seed(db, "Results", {"fiscal_year": 2026, "fiscal_quarter": "Q2"})
    assert EarningsWorkflowService()._documents(db, company, 2026, "Q2", []) == [expected]


def test_explicit_document_selection_is_preserved(db):
    company, doc = seed(db, "User-selected release")
    service = EarningsWorkflowService()
    assert service._documents(db, company, 2026, "Q2", [doc.id]) == [doc]
    with pytest.raises(ValueError, match="not found"):
        service._documents(db, company, 2026, "Q2", [doc.id + 999])


def test_structured_period_contradiction_overrides_title(db):
    company, _ = seed(db, "Q2 2026 results", {"fiscal_year": 2025, "fiscal_quarter": "Q2"})
    with pytest.raises(ValueError, match="period"):
        EarningsWorkflowService()._documents(db, company, 2026, "Q2", [])


def test_no_candidates_fails_honestly(db):
    company, doc = seed(db, "Q2 2026")
    db.delete(doc)
    db.commit()
    with pytest.raises(ValueError, match="period"):
        EarningsWorkflowService()._documents(db, company, 2026, "Q2", [])


@pytest.mark.parametrize("metadata", [{"fiscal_year": 2025}, {"fiscal_quarter": "Q1"}])
def test_partial_structured_contradiction_is_not_ignored(db, metadata):
    company, _ = seed(db, "Q2 2026 results", metadata)
    with pytest.raises(ValueError, match="period"):
        EarningsWorkflowService()._documents(db, company, 2026, "Q2", [])
