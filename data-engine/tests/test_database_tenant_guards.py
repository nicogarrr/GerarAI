"""Guards de tenant de app/core/database.py con SQLite real en memoria.

Los listeners (_scope_tenant_queries, _scope_tenant_dml,
_assign_tenant_to_new_rows) estan registrados sobre la clase Session al
importar el modulo, asi que una Session de prueba los ejerce de verdad:
no hay dobles del mecanismo de aislamiento. Se prueba: kwargs de engine
(pool/aislamiento solo para Postgres), escape include_all_tenants,
cuarentena de inferencias sin tenant, DML a granel acotado y su veto a
reasignar tenant_id, guards de before_flush (inferencias sin tenant,
cruzadas y legacy, asignacion y veto de tenant en filas nuevas,
inmutabilidad de tenant_id en sucias) y batch_refresh.

NO se prueba: get_db (dependencia FastAPI con principal HTTP; lote 2) ni
el bloque de migraciones forward-compat de init_db (rebuild SQLite de
thesis_versions; lote 2). Las inserciones "legacy" van por Core
(engine.connect) para saltarse before_flush deliberadamente: asi se crea
el estado prohibido que el guard debe detectar despues.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, delete, select, text, update
from sqlalchemy.orm import Session

import app.core.database as coredb
from app.models.entities import Base, Document, InferredInput


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def empresa(engine):
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO companies (ticker, name, exchange, currency,"
                " sector, industry, company_type, valuation_model,"
                " special_sources, special_risks, factor_tags,"
                " created_at, updated_at) VALUES"
                " ('PLTR', 'Palantir', 'NASDAQ', 'USD', 'Tech', 'Software',"
                " 'operating', 'standard_dcf', '[]', '[]', '[]',"
                " '2026-11-09 00:00:00', '2026-11-09 00:00:00')"
            )
        )
        conn.commit()
    return 1


def _documento(engine, *, tenant, titulo, source="unit-test"):
    with engine.connect() as conn:
        cur = conn.execute(
            text(
                "INSERT INTO documents (company_id, title, source_type, tenant_id,"
                " metadata, created_at, updated_at) VALUES (1, :t, :s, :tenant,"
                " '{}', '2026-11-09 00:00:00', '2026-11-09 00:00:00')"
            ),
            {"t": titulo, "s": source, "tenant": tenant},
        )
        conn.commit()
        return cur.lastrowid


def _titulos(engine) -> dict[int, str]:
    """Lectura Core sin listeners ORM: el estado real de la tabla."""
    with engine.connect() as conn:
        return {
            row.id: row.title
            for row in conn.execute(text("SELECT id, title FROM documents"))
        }


def test_engine_pool_kwargs_solo_para_postgres():
    settings = coredb.settings
    pg = coredb._engine_pool_kwargs("postgresql+psycopg://u:p@h/db", settings)
    assert pg == {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
    }
    assert coredb._engine_pool_kwargs("sqlite:///:memory:", settings) == {}


def test_engine_isolation_kwargs_solo_para_postgres():
    assert coredb._engine_isolation_kwargs("postgresql://u:p@h/db") == {
        "isolation_level": "READ COMMITTED"
    }
    assert coredb._engine_isolation_kwargs("sqlite:///:memory:") == {}


def test_select_sin_tenant_cuarentena_inferencias(engine, empresa):
    with engine.connect() as conn:  # legacy por Core: sin before_flush
        conn.execute(
            text(
                "INSERT INTO inferred_inputs (company_id, input_key, value, unit,"
                " base, source_urls, origin, tenant_id, created_at, updated_at)"
                " VALUES (1, 'wacc', 0.09, 'decimal', 'estimacion propia', '[]',"
                " 'llm', NULL, '2026-11-09 00:00:00', '2026-11-09 00:00:00')"
            )
        )
        conn.commit()
    with Session(engine) as db:  # sin info["tenant_id"]
        assert db.scalars(select(InferredInput)).all() == []
        visibles = db.scalars(
            select(InferredInput).execution_options(include_all_tenants=True)
        ).all()
        assert len(visibles) == 1


def test_dml_sobre_inferencias_sin_tenant_falla(engine, empresa):
    with Session(engine) as db:  # sin info["tenant_id"]
        with pytest.raises(RuntimeError, match="inferred input writes"):
            db.execute(delete(InferredInput))
        db.rollback()


def test_bulk_update_se_acota_al_tenant(engine, empresa):
    propio = _documento(engine, tenant=1, titulo="mio")
    ajeno = _documento(engine, tenant=2, titulo="suyo")
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        db.execute(
            update(Document)
            .where(Document.source_type == "unit-test")
            .values(title="actualizado")
        )
        db.commit()
    assert _titulos(engine) == {propio: "actualizado", ajeno: "suyo"}


def test_bulk_update_no_permite_reasignar_tenant(engine, empresa):
    _documento(engine, tenant=1, titulo="mio")
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        with pytest.raises(RuntimeError, match="Changing tenant_id"):
            db.execute(update(Document).values(tenant_id=2))
        db.rollback()
    # y via parametros dict (el guard inspecciona los dos caminos)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        with pytest.raises(RuntimeError, match="Changing tenant_id"):
            db.execute(update(Document), [{"tenant_id": 9}])
        db.rollback()


def test_flush_inferencia_sin_contexto_de_tenant_falla(engine, empresa):
    with Session(engine) as db:
        db.add(
            InferredInput(
                company_id=empresa,
                input_key="wacc",
                value=0.09,
                base="estimacion propia",
                source_urls=[],
            )
        )
        with pytest.raises(RuntimeError, match="inferred input writes"):
            db.flush()
        db.rollback()


def test_flush_inferencia_de_otro_tenant_falla(engine, empresa):
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        db.add(
            InferredInput(
                company_id=empresa,
                tenant_id=2,
                input_key="wacc",
                value=0.09,
                base="estimacion propia",
                source_urls=[],
            )
        )
        with pytest.raises(RuntimeError, match="Cross-tenant"):
            db.flush()
        db.rollback()


def test_flush_asigna_tenant_a_filas_nuevas(engine, empresa):
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        doc = Document(company_id=empresa, title="nuevo", source_type="unit-test")
        db.add(doc)
        db.flush()
        assert doc.tenant_id == 1
        db.rollback()


def test_flush_fila_nueva_de_otro_tenant_falla(engine, empresa):
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        db.add(
            Document(
                company_id=empresa, title="ajena", source_type="unit-test", tenant_id=2
            )
        )
        with pytest.raises(RuntimeError, match="Cross-tenant"):
            db.flush()
        db.rollback()


def test_flush_tenant_id_es_inmutable_en_filas_persistentes(engine, empresa):
    propio = _documento(engine, tenant=1, titulo="mio")
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        doc = db.get(Document, propio)
        doc.tenant_id = 2
        with pytest.raises(RuntimeError, match="tenant_id is immutable"):
            db.flush()
        db.rollback()
    assert _titulos(engine)[propio] == "mio"


def test_flush_inferencia_legacy_exige_recuperacion_auditada(engine, empresa):
    with engine.connect() as conn:  # fila legacy sin autor, por Core
        conn.execute(
            text(
                "INSERT INTO inferred_inputs (company_id, input_key, value, unit,"
                " base, source_urls, origin, tenant_id, created_at, updated_at)"
                " VALUES (1, 'wacc', 0.09, 'decimal', 'estimacion propia', '[]',"
                " 'llm', NULL, '2026-11-09 00:00:00', '2026-11-09 00:00:00')"
            )
        )
        conn.commit()
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        legacy = db.scalars(
            select(InferredInput).execution_options(include_all_tenants=True)
        ).one()
        legacy.value = 0.10
        with pytest.raises(RuntimeError, match="audited recovery"):
            db.flush()
        db.rollback()


def test_flush_filas_de_tenant_sin_contexto_con_auth_obligatoria(
    engine, empresa, monkeypatch
):
    monkeypatch.setattr(
        coredb, "settings", SimpleNamespace(research_auth_required=True)
    )
    with Session(engine) as db:  # sin info["tenant_id"]
        db.add(Document(company_id=empresa, title="anon", source_type="unit-test"))
        with pytest.raises(RuntimeError, match="tenant-owned writes"):
            db.flush()
        db.rollback()


def test_batch_refresh_recarga_los_valores(engine, empresa):
    a = _documento(engine, tenant=1, titulo="a")
    b = _documento(engine, tenant=1, titulo="b")
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        docs = db.scalars(select(Document).order_by(Document.id)).all()
        with engine.connect() as conn:
            conn.execute(text("UPDATE documents SET title = title || '2'"))
            conn.commit()
        coredb.batch_refresh(db, docs)
        assert [d.title for d in docs] == ["a2", "b2"]
        coredb.batch_refresh(db, [])  # no-op sin consulta
        db.rollback()
