from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import sources as sources_module
from app.core.database import get_db
from app.models.entities import Base, Company, SourceAudit, Tenant, ThesisVersion


def test_audits_payload_carries_thesis_version_date_and_reasons():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.add(Tenant(id=1, external_id="t"))
        company = Company(
            ticker="AAPL", name="Apple Inc", exchange="NASDAQ", currency="USD",
            company_type="holding", valuation_model="unassigned",
        )
        db.add(company)
        db.flush()
        thesis = ThesisVersion(tenant_id=1, company_id=company.id, version=7, status="draft_failed_audit", thesis_markdown="x", executive_summary="x")
        db.add(thesis)
        db.flush()
        db.add(SourceAudit(
            tenant_id=1, thesis_version_id=thesis.id, passed=False, source_coverage_score=100,
            unsupported_claims=["AAPL revenue grew"], data_conflicts=[], weak_claims=[],
            required_fixes=["Add source_id to every material claim."],
        ))
        db.commit()

        app = FastAPI()
        app.include_router(sources_module.router, prefix="/api/sources")
        app.dependency_overrides[get_db] = lambda: db
        rows = TestClient(app).get("/api/sources/audits?ticker=AAPL").json()

    assert len(rows) == 1
    row = rows[0]
    assert row["thesis_version"] == 7
    assert row["created_at"]
    assert row["unsupported_claims"] == ["AAPL revenue grew"]
    assert row["passed"] is False
    engine.dispose()
