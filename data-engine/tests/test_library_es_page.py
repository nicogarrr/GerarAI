"""Biblioteca en castellano (consulta expandida) y preguntas sobre el contenido de la página."""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Tenant
from app.models.entities import Base
from app.schemas import ChatPageContext
from app.services.chat_service import ChatService
from app.services.library_context import expand_query_en, retrieve_library_context
from app.services.rag import RAGIndex


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="es-page", name="Test")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        session.commit()
        yield session


def test_expand_spanish_terms_to_english():
    assert expand_query_en("¿Qué es el margen de seguridad?") == "margin of safety"
    assert "moat" in (expand_query_en("¿Qué es un foso?") or "")
    assert expand_query_en("capital allocation") is None


def test_spanish_question_also_searches_expanded_query(db, monkeypatch):
    queries = []

    def search(self, query, **kwargs):
        queries.append(query)
        return []

    monkeypatch.setattr(RAGIndex, "search", search)
    retrieve_library_context(db, "¿Qué es el margen de seguridad?")
    assert queries == ["¿Qué es el margen de seguridad?", "margin of safety"]


def test_page_content_question_says_it_has_no_page_data(db):
    page = ChatPageContext(path="/knowledge", label="Biblioteca", ticker=None)
    resp = asyncio.run(
        ChatService().answer(db, "¿cuántos documentos hay en esta página?", "portfolio", None, page=page)
    )
    assert resp.prompt_version == "page-content-unavailable-v1"
    assert "No tengo los datos de esta página (Biblioteca)" in resp.answer
    assert resp.sources == []
    assert resp.llm_trace["provider_calls"] == 0
