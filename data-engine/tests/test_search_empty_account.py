"""POST /api/search en una cuenta VACIA: 200 con 0 resultados, nunca error.

Regresion del ref. 760826059 (8-nov-2026): la cuenta QA vacia reventaba la
pagina /search al buscar. En el codigo actual la respuesta correcta es un
200 con items=[] y total 0 - la pagina pinta "sin evidencia". Estos tests
fijan ese contrato para que un cambio futuro no lo rompa: ni 500 del
servicio, ni 400 por filtros vacios, ni una forma de respuesta distinta a
la que el adaptador del frontend sabe leer (items + page_info).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.search import router as search_router
from app.core.database import Base, get_db
from app.models import Tenant


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
        tenant = Tenant(external_id="empty-qa", name="QA vacia")
        session.add(tenant)
        session.flush()
        tenant_id = tenant.id
        session.commit()

    app = FastAPI()
    app.include_router(search_router, prefix="/api/search")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = tenant_id
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


# Payload exacto que manda el frontend (lib/actions/research-tools.actions.ts).
def _payload(query: str, include_vector: bool) -> dict:
    return {
        "query": query,
        "ticker": None,
        "entity_types": [],
        "source_types": [],
        "statuses": [],
        "collection_id": None,
        "date_from": None,
        "date_to": None,
        "page_size": 50,
        "include_vector": include_vector,
    }


@pytest.mark.parametrize("include_vector", [False, True])
def test_cuenta_vacia_responde_200_con_cero_resultados(client, include_vector):
    resp = client.post("/api/search", json=_payload("cualquier cosa", include_vector))
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text[:400]}"
    body = resp.json()
    # La forma que el adaptador del frontend sabe leer: items + page_info.
    assert body["items"] == []
    assert body["page_info"]["total_items"] == 0
    assert body["query"] == "cualquier cosa"
    assert body["retrieval"]["vector_status"] in {"disabled", "available"} or body[
        "retrieval"
    ]["vector_status"].startswith("unavailable:")


def test_cuenta_vacia_con_query_solo_simbolos_tampoco_revienta(client):
    resp = client.post("/api/search", json=_payload("!!!@@@---", False))
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text[:400]}"
    assert resp.json()["page_info"]["total_items"] == 0
