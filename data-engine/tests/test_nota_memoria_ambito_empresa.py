"""Notas de memoria: una nota de una empresa es de esa empresa.

`POST /api/memory/memory-items` con ticker (o company_id) y sin ámbito guardaba
`scope="portfolio"` (el valor por defecto). La memoria del chat trae, para
cualquier empresa, sus notas Y todas las de ámbito «portfolio»: la nota de ACME
salía como contexto en el chat de BETA (también las ya guardadas así). Ahora una nota con empresa queda con
ámbito «company» (igual que «recuerda …» en el chat) y una nota «company» sin
empresa se rechaza: no aparecería en ningún sitio."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.memory import router as memory_router
from app.core.database import Base, get_db
from app.models import Company, MemoryItem, Tenant
from app.services.memory_service import MemoryService


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    ids: dict[str, int] = {}
    with factory() as db:
        mine = Tenant(external_id="nota-ambito-mine", name="Mine")
        db.add(mine)
        db.flush()
        ids["mine"] = mine.id
        acme = Company(ticker="ACME", name="Acme", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        beta = Company(ticker="BETA", name="Beta", exchange="T", currency="USD",
                       company_type="research_candidate", valuation_model="unassigned")
        db.add_all([acme, beta])
        db.flush()
        ids.update(acme=acme.id, beta=beta.id)
        db.commit()

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")

    def _get_db():
        with factory() as s:
            s.info["tenant_id"] = ids["mine"]
            yield s

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), ids, factory


def _post(client, **body):
    return client.post("/api/memory/memory-items", json={"importance": 9, **body})


def _memoria_del_chat(factory, ids, ticker):
    with factory() as db:
        db.info["tenant_id"] = ids["mine"]
        company = db.get(Company, ids[ticker])
        return [m.item.content for m in MemoryService().retrieve(db, "margen", company=company)]


@pytest.mark.parametrize("ref", [{"ticker": "ACME"}, {"company_id": "acme"}])
def test_nota_de_una_empresa_no_sale_en_el_chat_de_otra(world, ref):
    client, ids, factory = world
    body = {k: (ids[v] if k == "company_id" else v) for k, v in ref.items()}
    res = _post(client, content="ACME: el margen bruto baja por aranceles", **body)
    assert res.status_code == 200, res.text
    assert res.json()["scope"] == "company"
    assert res.json()["company_id"] == ids["acme"]
    assert "ACME: el margen bruto baja por aranceles" in _memoria_del_chat(factory, ids, "acme")
    assert _memoria_del_chat(factory, ids, "beta") == []


def test_nota_de_cartera_sin_empresa_sigue_en_todos_los_chats(world):
    client, ids, factory = world
    res = _post(client, content="Cartera: margen de seguridad mínimo del 20 %")
    assert res.status_code == 200, res.text
    assert res.json()["scope"] == "portfolio"
    assert res.json()["company_id"] is None
    assert _memoria_del_chat(factory, ids, "beta") == ["Cartera: margen de seguridad mínimo del 20 %"]


def test_ambito_empresa_sin_empresa_se_rechaza(world):
    client, _ids, factory = world
    res = _post(client, content="nota sin empresa", scope="company")
    assert res.status_code == 400, res.text
    with factory() as db:
        assert db.query(MemoryItem).count() == 0


def test_nota_vieja_de_empresa_con_ambito_cartera_tampoco_sale_en_otra(world):
    _client, ids, factory = world
    with factory() as db:
        db.add(MemoryItem(tenant_id=ids["mine"], company_id=ids["acme"], scope="portfolio",
                          memory_type="note", importance=9, content="ACME: margen guardado antes",
                          status="active", source_type="user"))
        db.commit()
    assert _memoria_del_chat(factory, ids, "beta") == []
    assert _memoria_del_chat(factory, ids, "acme") == ["ACME: margen guardado antes"]
