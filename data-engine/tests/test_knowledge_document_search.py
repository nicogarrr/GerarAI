"""Búsqueda de la Biblioteca: /knowledge/documents/search (título, autor, ticker; por tenant)."""
import asyncio

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import knowledge
from app.core.database import Base, get_db
from app.models import KnowledgeDocument, Tenant


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        mine, other = Tenant(external_id="bib-a", name="A"), Tenant(external_id="bib-b", name="B")
        session.add_all([mine, other])
        session.flush()
        rows = {
            mine.id: [
                ("Carta a los accionistas 2019", "Warren Buffett", "BRK.B"),
                ("Margin of Safety", "Seth Klarman", None),
                ("Notas sobre Inditex", None, "ITX.MC"),
                ("Descuento del 50%_raro", "Anónimo", None),
            ],
            other.id: [("Carta secreta de otro tenant", "Warren Buffett", "BRK.B")],
        }
        for tenant_id, docs in rows.items():
            session.info["tenant_id"] = tenant_id
            for i, (title, author, ticker) in enumerate(docs):
                session.add(KnowledgeDocument(title=title, author=author, ticker=ticker,
                    checksum=f"bib-{tenant_id}-{i}", document_type="personal_note", language="es", status="ready"))
            session.flush()
        session.commit()
        session.info["tenant_id"] = mine.id
        session.info["other_tenant"] = other.id
        yield session


def _get(db, path):
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/knowledge")
    app.dependency_overrides[get_db] = lambda: db

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(run())


def _titles(response):
    assert response.status_code == 200, response.text
    return sorted(item["title"] for item in response.json()["items"])


def test_search_matches_title_author_and_ticker_case_insensitively(db):
    assert _titles(_get(db, "/knowledge/documents/search?q=carta")) == ["Carta a los accionistas 2019"]
    assert _titles(_get(db, "/knowledge/documents/search?q=KLARMAN")) == ["Margin of Safety"]
    assert _titles(_get(db, "/knowledge/documents/search?q=itx")) == ["Notas sobre Inditex"]
    body = _get(db, "/knowledge/documents/search?q=buffett%20carta").json()
    assert body["total"] == 1 and body["query"] == "buffett carta"


def test_search_is_tenant_scoped(db):
    body = _get(db, "/knowledge/documents/search?q=buffett").json()
    assert [item["title"] for item in body["items"]] == ["Carta a los accionistas 2019"]
    assert body["total"] == 1
    db.info["tenant_id"] = db.info["other_tenant"]
    assert _titles(_get(db, "/knowledge/documents/search?q=carta")) == ["Carta secreta de otro tenant"]


def test_search_treats_wildcards_literally_and_bounds_input(db):
    assert _titles(_get(db, "/knowledge/documents/search?q=%25")) == ["Descuento del 50%_raro"]
    assert _titles(_get(db, "/knowledge/documents/search?q=_")) == ["Descuento del 50%_raro"]
    empty = _get(db, "/knowledge/documents/search?q=%20%20").json()
    assert empty == {"items": [], "total": 0, "query": ""}
    assert _get(db, "/knowledge/documents/search?q=" + "x" * 201).status_code == 422
    assert _get(db, "/knowledge/documents/search?q=carta&limit=500").status_code == 422


def test_search_paginates_with_total(db):
    first = _get(db, "/knowledge/documents/search?q=a&limit=2").json()
    second = _get(db, "/knowledge/documents/search?q=a&limit=2&offset=2").json()
    assert first["total"] == second["total"] == 4
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(ids)) == 4
