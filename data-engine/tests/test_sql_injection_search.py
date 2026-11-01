"""SQL injection protection tests for search endpoints.

Fulfills: VAL-SEC-003 (SQL injection protection on search endpoints)
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.search import router as search_router
from app.core.database import Base, get_db
from app.models.entities import Company


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
        session.info["tenant_id"] = "sqli-test-tenant"
        company = Company(
            ticker="AAPL",
            name="Apple Inc.",
            exchange="NASDAQ",
            currency="USD",
            company_type="research_candidate",
            valuation_model="unassigned",
        )
        session.add(company)
        session.commit()

    test_app = FastAPI()
    test_app.include_router(search_router, prefix="/api/search")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = "sqli-test-tenant"
            yield s

    test_app.dependency_overrides[get_db] = _get_db
    return TestClient(test_app)


SQLI_PAYLOADS = [
    "' OR '1'='1",
    "' OR 1=1 --",
    "'; DROP TABLE companies; --",
    "' UNION SELECT null, null, null --",
    "admin'--",
    "1' ORDER BY 1--+",
    "1' UNION ALL SELECT 'a', 'b'--",
    "1 AND 1=1",
    "1 AND 1=2",
    "'; EXEC xp_cmdshell('dir'); --",
    "SLEEP(5) /*' or SLEEP(5) or '\" or SLEEP(5) or \"*/",
    "benchmark(50000000,MD5(1))",
]


@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_universal_search_sql_injection_payloads(client: TestClient, payload: str):
    """Search endpoints sanitize input and never execute raw SQL injection."""
    resp = client.post(
        "/api/search",
        json={
            "query": payload,
            "ticker": "AAPL",
            "page": 1,
            "page_size": 20,
        },
    )
    # The endpoint must respond cleanly with 200 (or validation error), never 500 or DB error
    assert resp.status_code == 200, f"Failed on payload {payload}: {resp.text}"
    data = resp.json()
    assert "items" in data
    assert "page_info" in data


def test_search_ticker_sql_injection(client: TestClient):
    """Ticker parameter is also safely handled."""
    resp = client.post(
        "/api/search",
        json={
            "query": "revenue",
            "ticker": "' OR 1=1 --",
            "page": 1,
            "page_size": 10,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
