"""Rutas /knowledge-graph: filtro por ticker y tipos, 404 y sync.

Sobre main solo estaba cubierto el sync; el GET con resolucion de ticker,
el parseo de node_types y el vecindario no tenian cobertura.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import knowledge_graph as mod
from app.api.routes.knowledge_graph import (
    knowledge_graph,
    knowledge_graph_neighbors,
    sync_knowledge_graph,
)
from app.models.entities import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        yield db
    engine.dispose()


class _FakeService:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else {"ok": True}
        self.error = error
        self.calls = []

    def sync(self, db):
        if self.error:
            raise self.error
        return self.result

    def graph(self, db, node_types=None, company_id=None, limit=500):
        self.calls.append({"node_types": node_types, "company_id": company_id, "limit": limit})
        return self.result

    def neighborhood(self, db, node_id, depth=2):
        if self.error:
            raise self.error
        return {"node_id": node_id, "depth": depth}


def test_sync_error_de_validacion_es_400(db, monkeypatch):
    monkeypatch.setattr(mod, "KnowledgeGraphService", lambda: _FakeService(error=ValueError("x")))
    with pytest.raises(HTTPException) as exc:
        sync_knowledge_graph(db=db)
    assert exc.value.status_code == 400


def test_graph_ticker_desconocido_es_404(db, monkeypatch):
    monkeypatch.setattr(mod, "resolve_company", lambda db_, ticker: None)
    with pytest.raises(HTTPException) as exc:
        knowledge_graph(ticker="NOPE", db=db)
    assert exc.value.status_code == 404


def test_graph_parsea_tipos_y_resuelve_ticker(db, monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(mod, "KnowledgeGraphService", lambda: service)
    monkeypatch.setattr(mod, "resolve_company", lambda db_, ticker: SimpleNamespace(id=42))
    out = knowledge_graph(node_types="company, persona ,,tema", ticker="asts", limit=50, db=db)
    assert out == {"ok": True}
    call = service.calls[0]
    assert call["node_types"] == {"company", "persona", "tema"}
    assert call["company_id"] == 42
    assert call["limit"] == 50


def test_graph_sin_filtros_pasa_none(db, monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(mod, "KnowledgeGraphService", lambda: service)
    knowledge_graph(db=db)
    call = service.calls[0]
    assert call["node_types"] is None
    assert call["company_id"] is None


def test_neighbors_nodo_desconocido_es_404(db, monkeypatch):
    monkeypatch.setattr(
        mod, "KnowledgeGraphService", lambda: _FakeService(error=ValueError("nodo 9 no existe"))
    )
    with pytest.raises(HTTPException) as exc:
        knowledge_graph_neighbors(9, db=db)
    assert exc.value.status_code == 404
    assert "nodo 9" in exc.value.detail


def test_neighbors_camino_feliz_con_profundidad(db, monkeypatch):
    monkeypatch.setattr(mod, "KnowledgeGraphService", lambda: _FakeService())
    assert knowledge_graph_neighbors(5, depth=3, db=db) == {"node_id": 5, "depth": 3}
