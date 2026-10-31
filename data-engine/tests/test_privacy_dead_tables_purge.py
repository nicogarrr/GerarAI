"""El borrado de cuenta purga tambien las tablas con tenant_id sin modelo.

Migraciones viejas crearon tablas cuyo modelo desaparecio (p. ej.
thesis_backtest_runs); delete_account enumeraba solo Base.metadata y sus
filas sobrevivian al borrado. MEDIDO en la cadena 0001->0115: 7 tablas asi.

Corre en el job Postgres (crea y destruye su BD scratch migrada a head);
en sqlite/local hace skip salvo el test de cobertura sin tablas muertas.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select

from tests.test_0114_fk_ondelete import _scratch
from tests.test_alembic_chain import _url_postgres_ci

_TABLAS_MUERTAS = {
    "api_latency_windows",
    "evidence_coverage_snapshots",
    "thesis_backtest_cells",
    "thesis_backtest_results",
    "thesis_backtest_runs",
    "thesis_hit_rate_cells",
    "thesis_realized_returns",
}


def _fila_generica(table: sa.Table, tenant_id: int, run_id: int | None = None) -> dict:
    import datetime

    row = {}
    for col in table.columns:
        if col.name == "id" or col.default is not None or col.server_default is not None:
            continue
        if not col.nullable and col.name != "tenant_id":
            t = str(col.type).upper()
            if col.name == "run_id" and run_id is not None:
                row[col.name] = run_id
            elif t.startswith(("INT", "BIGINT", "SMALLINT")):
                row[col.name] = 1
            elif t.startswith(("JSON", "JSONB")):
                row[col.name] = {}
            elif t.startswith("BOOL"):
                row[col.name] = False
            elif t.startswith("DATE"):
                row[col.name] = datetime.date(2026, 10, 1)
            elif t.startswith(("TIMESTAMP", "DATETIME")):
                row[col.name] = datetime.datetime(2026, 10, 1)
            else:
                ln = getattr(col.type, "length", None) or 32
                row[col.name] = f"purge-{col.name}"[:ln]
    row["tenant_id"] = tenant_id
    return row


def test_cobertura_sin_tablas_muertas_en_sqlite():
    """Sin tablas ajenas a los modelos, el helper devuelve exactamente las
    tablas de modelo con tenant_id: comportamiento inalterado en sqlite."""
    from app.core.database import Base, engine
    from app.services.privacy_service import _tenant_scoped_tables

    esperado = [
        t.name
        for t in reversed(Base.metadata.sorted_tables)
        if "tenant_id" in t.columns and t.name != "tenants"
    ]
    with engine.connect() as conn:
        obtenido = [t.name for t in _tenant_scoped_tables(conn)]
    assert obtenido == esperado
    assert not (_TABLAS_MUERTAS & set(obtenido))


def test_delete_account_purga_tablas_sin_modelo_en_ci_postgres(monkeypatch):
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo en el job Postgres con CAVAAI_ORIGINAL_DATABASE_URL")

    from app.core.database import Base
    from app.models import Tenant, WatchItem
    from app.services import privacy_service
    from app.services.privacy_service import PrivacyService, _tenant_scoped_tables

    scratch, scratch_url, admin = _scratch(url)
    engine = sa.create_engine(scratch_url)
    try:
        with engine.begin() as conn:
            tenant_id = conn.execute(
                sa.insert(Tenant.__table__).values(external_id="purge-dead", name="P")
            ).inserted_primary_key[0]
            md = sa.MetaData()
            runs = sa.Table("thesis_backtest_runs", md, autoload_with=conn)
            cells = sa.Table("thesis_backtest_cells", md, autoload_with=conn)
            latency = sa.Table("api_latency_windows", md, autoload_with=conn)
            run_id = conn.execute(
                sa.insert(runs).values(**_fila_generica(runs, tenant_id))
            ).inserted_primary_key[0]
            conn.execute(sa.insert(cells).values(**_fila_generica(cells, tenant_id, run_id)))
            conn.execute(sa.insert(latency).values(**_fila_generica(latency, tenant_id)))
            conn.execute(
                sa.insert(WatchItem.__table__).values(
                    tenant_id=tenant_id, symbol="MUERTA"
                )
            )

        with engine.connect() as conn:
            tablas = [t.name for t in _tenant_scoped_tables(conn)]
        assert set(tablas) >= _TABLAS_MUERTAS
        # hijos muertos antes que sus padres muertos y antes que los modelos
        assert tablas.index("thesis_backtest_cells") < tablas.index("thesis_backtest_runs")
        modelo_min = min(
            tablas.index(t.name)
            for t in Base.metadata.sorted_tables
            if "tenant_id" in t.columns and t.name != "tenants"
        )
        assert max(tablas.index(n) for n in _TABLAS_MUERTAS) < modelo_min

        monkeypatch.setattr(
            "app.services.privacy_service.DocumentStore.delete", lambda _s, uri: True
        )
        monkeypatch.setattr(
            "app.services.privacy_service.DocumentStore.delete_tenant_prefix",
            lambda _s, tid: 0,
        )
        monkeypatch.setattr(
            "app.services.privacy_service.RAGIndex.delete_tenant_points",
            lambda _s, tid: 0,
        )
        monkeypatch.setattr(
            "app.services.privacy_service.PrivacyService._delete_knowledge_vectors",
            staticmethod(lambda tenant_id: 0),
        )
        monkeypatch.setattr(
            "app.services.privacy_service.purge_llm_response_cache", lambda **kw: 0
        )
        monkeypatch.setattr(privacy_service, "engine", engine)

        from sqlalchemy.orm import Session

        db = Session(engine)
        db.info["tenant_id"] = tenant_id
        db.info["user_id"] = "user-purge"
        try:
            result = PrivacyService().delete_account(
                db, confirmation="ELIMINAR MI CUENTA"
            )
        finally:
            db.close()

        assert result["already_deleted"] is False
        assert "thesis_backtest_runs" in result["tables"]
        assert "watch_items" in result["tables"]
        with engine.connect() as conn:
            for tabla in _TABLAS_MUERTAS | {"watch_items"}:
                restantes = conn.execute(
                    sa.text(f"select count(*) from {tabla} where tenant_id = :t"),
                    {"t": tenant_id},
                ).scalar_one()
                assert restantes == 0, f"{tabla} conservo {restantes} filas"
            estado = conn.execute(
                select(Tenant.__table__.c.status).where(
                    Tenant.__table__.c.id == tenant_id
                )
            ).scalar_one()
            assert estado == "deleted"
            auditoria = conn.execute(
                select(func.count())
                .select_from(sa.table("privacy_audit_events"))
                .where(sa.column("tenant_external_id") == "purge-dead")
            ).scalar_one()
            assert auditoria >= 1
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()
