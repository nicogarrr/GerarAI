"""privacy_service: tablas muertas (orden y ciclo), guards de tenant y
fallos externos agregados del borrado de cuenta.

SQLite real en memoria (Base.metadata.create_all); las tablas "muertas" se
crean con DDL crudo para simular migraciones viejas sin modelo. Los clientes
externos (DocumentStore, RAGIndex, cache LLM, Qdrant) son dobles que fallan
o devuelven valores fijos: no hay red ni servicios reales. ``SessionLocal``
se dobla al engine scratch porque ``_audit`` escribe con la factoria del
modulo, no con la sesion recibida.

No se prueba aqui: el borrado feliz completo ni la exportacion feliz
(cubiertos en test_privacy_account_lifecycle.py y test_privacy_export_extended.py),
ni el purgado real en Postgres del job CI (test_privacy_dead_tables_purge.py).
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.services.privacy_service as ps
from app.models import Tenant
from app.models.entities import Base, Document, PrivacyAuditEvent
from app.services.privacy_service import (
    DELETE_CONFIRMATION,
    PrivacyPartialFailure,
    PrivacyService,
    _tenant_scoped_tables,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


# -- _tenant_scoped_tables ------------------------------------------------------


def test_tablas_sin_muertas_solo_modelos(engine):
    esperado = [
        t.name
        for t in reversed(Base.metadata.sorted_tables)
        if "tenant_id" in t.columns and t.name != "tenants"
    ]
    with engine.connect() as conn:
        obtenido = [t.name for t in _tenant_scoped_tables(conn)]
    assert obtenido == esperado


def test_tablas_muertas_hijos_antes_que_padres(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE dead_parent (id INTEGER PRIMARY KEY, tenant_id INTEGER)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE dead_child (id INTEGER PRIMARY KEY, tenant_id INTEGER,"
            " parent_id INTEGER REFERENCES dead_parent(id))"
        )
    with engine.connect() as conn:
        nombres = [t.name for t in _tenant_scoped_tables(conn)]
    # Las muertas van primero, hijos antes que padres por sus propias FKs.
    assert nombres[:2] == ["dead_child", "dead_parent"]


def test_tablas_muertas_ciclo_orden_alfabetico_estable(engine):
    # Ciclo dead_a <-> dead_b: no hay orden topologico; el fallback alfabetico
    # elige dead_a como raiz y reversed() la deja detras de dead_b.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE dead_a (id INTEGER PRIMARY KEY, tenant_id INTEGER,"
            " b_id INTEGER REFERENCES dead_b(id))"
        )
        conn.exec_driver_sql(
            "CREATE TABLE dead_b (id INTEGER PRIMARY KEY, tenant_id INTEGER,"
            " a_id INTEGER REFERENCES dead_a(id))"
        )
    with engine.connect() as conn:
        nombres = [t.name for t in _tenant_scoped_tables(conn)]
    assert nombres[:2] == ["dead_b", "dead_a"]


# -- Guards de tenant ------------------------------------------------------------


def test_export_sin_tenant_lanza(db):
    with pytest.raises(ValueError, match="Tenant context is required"):
        PrivacyService().export_account(db)


def test_delete_sin_tenant_lanza(db):
    with pytest.raises(ValueError, match="Tenant context is required"):
        PrivacyService().delete_account(db, confirmation=DELETE_CONFIRMATION)


def test_delete_tenant_inexistente_es_idempotente(db, engine, monkeypatch):
    monkeypatch.setattr(ps, "SessionLocal", sessionmaker(bind=engine))
    db.info["tenant_id"] = 999999
    db.info["user_id"] = "user-test"
    out = PrivacyService().delete_account(
        db, confirmation=DELETE_CONFIRMATION, reason="test_reason"
    )
    assert out["status"] == "deleted"
    assert out["already_deleted"] is True
    with Session(engine) as check:
        eventos = check.scalars(select(PrivacyAuditEvent)).all()
    assert len(eventos) == 1
    assert eventos[0].event_type == "account.delete"
    assert eventos[0].detail["status"] == "already_deleted"
    assert eventos[0].detail["reason"] == "test_reason"


# -- Fallos externos agregados ----------------------------------------------------


class _StoreQueFalla:
    def delete(self, uri):
        raise RuntimeError("object storage caido")

    def delete_tenant_prefix(self, tenant_id):
        return 0


class _RagQueFalla:
    def delete_tenant_points(self, tenant_id):
        raise RuntimeError("qdrant documentos caido")


def _cache_que_falla(*, tenant_id):
    raise RuntimeError("cache llm caida")


def _knowledge_que_falla(tenant_id):
    raise RuntimeError("qdrant conocimiento caido")


def test_delete_fallos_externos_se_agregan_y_no_se_borra(db, monkeypatch):
    tenant = Tenant(external_id="ext-fallos", name="Tenant Fallos")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    db.info["user_id"] = "user-test"
    db.add(Document(
        tenant_id=tenant.id, title="Doc con bytes", source_type="upload",
        storage_uri="s3://bucket/clave",
    ))
    db.commit()

    monkeypatch.setattr(ps, "DocumentStore", _StoreQueFalla)
    monkeypatch.setattr(ps, "RAGIndex", _RagQueFalla)
    monkeypatch.setattr(ps, "purge_llm_response_cache", _cache_que_falla)
    monkeypatch.setattr(
        ps.PrivacyService, "_delete_knowledge_vectors",
        staticmethod(_knowledge_que_falla),
    )

    with pytest.raises(PrivacyPartialFailure) as excinfo:
        PrivacyService().delete_account(db, confirmation=DELETE_CONFIRMATION)
    assert set(excinfo.value.failures) == {
        "object_storage",
        "document_vectors",
        "knowledge_vectors",
        "llm_cache",
    }
    # Falla cerrado: el tenant sigue activo, Postgres intacto.
    assert db.get(Tenant, tenant.id).status == "active"


# -- Vectores de conocimiento -----------------------------------------------------


def test_delete_knowledge_vectors_ok(monkeypatch):
    import qdrant_client

    from app.services.knowledge_rag import store as knowledge_store_mod

    captura = {}

    class _QdrantFalso:
        def __init__(self, url):
            captura["url"] = url

    class _KnowledgeStoreFalso:
        def __init__(self, client, collection, dims):
            captura["collection"] = collection
            captura["dims"] = dims

        def delete_tenant(self, tenant_id):
            captura["tenant_id"] = tenant_id
            return 7

    monkeypatch.setattr(qdrant_client, "QdrantClient", _QdrantFalso)
    monkeypatch.setattr(knowledge_store_mod, "KnowledgeStore", _KnowledgeStoreFalso)
    assert PrivacyService._delete_knowledge_vectors(42) == 7
    assert captura["tenant_id"] == 42
    assert isinstance(captura["url"], str) and captura["url"]
    assert isinstance(captura["dims"], int)
