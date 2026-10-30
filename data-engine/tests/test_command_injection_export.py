"""Command injection protection tests on export and file operations.

Fulfills: VAL-SEC-005 (Command injection protection on file operations)
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.thesis import router as thesis_router
from app.core.database import Base, get_db
from app.models.entities import Company, ThesisSection, ThesisVersion


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as session:
        session.info["tenant_id"] = "cmd-test-tenant"
        company = Company(
            ticker="AAPL",
            name="Apple Inc.",
            exchange="NASDAQ",
            currency="USD",
            company_type="research_candidate",
            valuation_model="unassigned",
        )
        session.add(company)
        session.flush()

        thesis = ThesisVersion(
            company_id=company.id,
            version=1,
            thesis_markdown="# Apple Investment Thesis",
            executive_summary="Solid balance sheet and ecosystem.",
            rating="buy",
            status="published",
        )
        session.add(thesis)
        session.flush()

        section = ThesisSection(
            thesis_version_id=thesis.id,
            company_id=company.id,
            section_key="ecosystem_moat",
            title="Ecosystem Moat",
            body="High retention rate and recurring services revenue.",
            order_index=1,
        )
        session.add(section)
        session.commit()

    test_app = FastAPI()
    test_app.include_router(thesis_router, prefix="/api/thesis")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = "cmd-test-tenant"
            yield s

    test_app.dependency_overrides[get_db] = _get_db
    return TestClient(test_app)


COMMAND_INJECTION_PAYLOADS = [
    "AAPL; whoami",
    "AAPL$(id)",
    "AAPL`calc`",
    "AAPL && dir",
    "AAPL | cat /etc/passwd",
    "AAPL; rm -rf /",
    "AAPL; sleep 5",
]


def test_valid_thesis_export_returns_safe_filename(client: TestClient):
    """Valid export returns safe content disposition without command execution."""
    resp = client.get("/api/thesis/AAPL/epub")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/epub+zip"
    cd = resp.headers.get("content-disposition", "")
    assert cd == 'attachment; filename="gerarai-thesis-AAPL-v1.epub"'
    # Verify valid zip bytes (EPUB is a zip archive)
    assert resp.content[:2] == b"PK"


@pytest.mark.parametrize("payload", COMMAND_INJECTION_PAYLOADS)
def test_export_with_shell_metacharacters(client: TestClient, payload: str):
    """Shell metacharacters in ticker do not cause command execution or 500 error."""
    resp = client.get(f"/api/thesis/{payload}/epub")
    # Must never return 500 or execute shell command; returns 404 safely
    assert resp.status_code in (404, 422, 400), f"Unexpected status {resp.status_code} for {payload}"
    assert "Internal Server Error" not in resp.text
