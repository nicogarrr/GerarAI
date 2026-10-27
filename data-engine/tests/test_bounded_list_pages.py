"""Bounded page regression tests, using the real route functions and tenant ORM."""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.knowledge import documents_page, get_document, principles_page
from app.api.routes.portfolio import transactions_page
from app.core.database import Base
from app.models import (
    Company,
    InvestmentPrinciple,
    KnowledgeCollection,
    KnowledgeDocument,
    Tenant,
    Transaction,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenants = [Tenant(external_id=f"page-{i}", name=f"Page {i}") for i in range(2)]
        session.add_all(tenants)
        session.flush()
        for tenant in tenants:
            session.info["tenant_id"] = tenant.id
            collection = KnowledgeCollection(name="Letters", slug="letters", collection_type="custom")
            session.add(collection)
            session.flush()
            for i in range(351):
                document = KnowledgeDocument(title=f"Document {i}", checksum=f"doc-{tenant.id}-{i}",
                    collection_id=collection.id, document_type="personal_note", language="es", status="ready")
                session.add(document)
                session.flush()
                session.add(InvestmentPrinciple(knowledge_document_id=document.id,
                    principle=f"Principle {i}", principle_fingerprint=f"p-{tenant.id}-{i}",
                    category="quality", exact_fragment="Evidence", confidence=Decimal("0.9"),
                    status="approved" if i == 0 else "proposed"))
            session.commit()
        session.info["tenant_id"] = tenants[0].id
        yield session
    engine.dispose()


def test_documents_total_collection_counts_and_old_deep_link(db):
    first = documents_page(limit=50, offset=0, db=db)
    assert len(first["items"]) == 50
    assert first["total"] == 351  # not 702 across tenants, nor capped at 200
    assert list(first["collection_counts"].values()) == [351]
    pages = [documents_page(limit=50, offset=i, db=db) for i in range(0, 351, 50)]
    ids = [item["id"] for page in pages for item in page["items"]]
    assert len(set(ids)) == len(ids) == 351
    old = get_document(document_id=ids[-1], db=db)
    assert old["title"] == "Document 0"
    assert old["id"] not in [item["id"] for item in first["items"]]
    other_id = max(ids) + 1
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        get_document(document_id=other_id, db=db)
    assert error.value.status_code == 404


def test_principle_filter_precedes_pagination_beyond_old_300_cap(db):
    approved = principles_page(status="approved", limit=50, offset=0, db=db)
    assert approved["total"] == 1
    assert approved["proposed_total"] == 350
    assert len(approved["items"]) == 1
    assert approved["items"][0]["principle"] == "Principle 0"
    all_pages = [principles_page(status=None, limit=50, offset=i, db=db) for i in range(0, 351, 50)]
    ids = [item["id"] for page in all_pages for item in page["items"]]
    assert len(set(ids)) == len(ids) == 351
    assert not principles_page(status="approved", limit=50, offset=50, db=db)["items"]


def test_transactions_201_equal_dates_no_gaps_and_tenant_total(db):
    tenant_id = db.info["tenant_id"]
    company = Company(ticker="PAGE", name="Paging Company", exchange="TEST", company_type="operating", valuation_model="dcf")
    db.add(company)
    db.flush()
    for i in range(201):
        db.add(Transaction(company_id=company.id, action="buy", quantity=Decimal(1),
            price=Decimal(10), currency="EUR", trade_date=date(2026, 1, 1),
            created_at=datetime(2026, 1, 1, tzinfo=UTC)))
    db.commit()
    first = transactions_page(limit=50, offset=0, db=db)
    assert first["total"] == 201
    ids = [item["id"] for offset in range(0, 201, 50)
           for item in transactions_page(limit=50, offset=offset, db=db)["items"]]
    assert len(set(ids)) == len(ids) == 201
    assert ids == sorted(ids, reverse=True)
    assert transactions_page(limit=50, offset=250, db=db)["items"] == []
    db.info["tenant_id"] = tenant_id + 1
    assert transactions_page(limit=50, offset=0, db=db) == {"items": [], "total": 0}


def test_http_static_page_routes_precede_document_id_and_enforce_bounds(db):
    from fastapi import FastAPI

    from app.api.routes import knowledge, portfolio
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(knowledge.router, prefix="/knowledge")
    app.include_router(portfolio.router, prefix="/portfolio")
    app.dependency_overrides[get_db] = lambda: db
    # Sync routes run in FastAPI threadpool; fixture uses one shared SQLite connection.
    import asyncio

    import httpx

    async def check():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/knowledge/documents/page?limit=50&offset=350")
            assert response.status_code == 200
            assert response.json()["total"] == 351
            assert len(response.json()["items"]) == 1
            response = await client.get("/knowledge/principles/page?status=approved")
            assert response.status_code == 200
            assert response.json()["total"] == 1
            for path in ("/knowledge/documents/page", "/knowledge/principles/page", "/portfolio/transactions/page"):
                assert (await client.get(path + "?limit=201")).status_code == 422
                assert (await client.get(path + "?offset=-1")).status_code == 422

    asyncio.run(check())
