"""0127: tabla ``declared_input_values`` (inputs declarados con rango, estado y fuente).

Feature aprobada por Nico (pipeline automatico de inputs que faltan). Se prueba
el ciclo upgrade/downgrade/upgrade en sqlite y en Postgres (job de CI o el PG
local si ``CI=true``), que el modelo declara las mismas columnas e indices que
la migracion, y que la unicidad vale solo para la fila vigente
(``superseded_at IS NULL``) para conservar el historico.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from alembic import command
from tests.test_alembic_chain import VERSIONS_DIR, _url_postgres_ci

TABLE = "declared_input_values"
REVISION = "0127_declared_input_values"
COLUMNS = {
    "id",
    "tenant_id",
    "company_id",
    "input_key",
    "segment_key",
    "low",
    "base",
    "high",
    "unit",
    "status",
    "method",
    "source_url",
    "source_quote",
    "document_id",
    "analyst_firm",
    "as_of",
    "model_family",
    "input_set_version",
    "fingerprint",
    "metadata",
    "superseded_at",
    "created_at",
    "updated_at",
}
INDEXES = {
    "ix_declared_input_values_tenant_id",
    "ix_declared_input_values_company_id",
    "uq_declared_input_current",
}


def _cfg(url: str, monkeypatch) -> Config:
    from app.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    return cfg


def _module():
    spec = importlib.util.spec_from_file_location("migration0127", VERSIONS_DIR / f"{REVISION}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _insert(conn, *, superseded: datetime | None, key: str = "penetration_target") -> None:
    now = datetime.now(UTC)
    conn.execute(
        sa.text(
            "INSERT INTO declared_input_values (tenant_id, company_id, input_key, segment_key, "
            "base, unit, status, method, metadata, superseded_at, created_at, updated_at) "
            "VALUES (1, 1, :key, 'us', 0.2, 'ratio', 'estimado', 'infer', '{}', :sup, :now, :now)"
        ),
        {"key": key, "sup": superseded, "now": now},
    )


def test_0127_es_el_siguiente_al_head_anterior() -> None:
    module = _module()
    assert module.revision == REVISION
    assert module.down_revision == "0126_email_user_prefs"
    assert len(module.revision) <= 32


def test_0127_upgrade_downgrade_upgrade_en_sqlite(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    url = f"sqlite:///{tmp_path}/mig0127.db"
    cfg = _cfg(url, monkeypatch)
    try:
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        inspector = sa.inspect(engine)
        assert TABLE in inspector.get_table_names()
        assert {c["name"] for c in inspector.get_columns(TABLE)} == COLUMNS
        assert {ix["name"] for ix in inspector.get_indexes(TABLE)} >= INDEXES

        with engine.begin() as conn:
            conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
            _insert(conn, superseded=datetime(2026, 1, 1, tzinfo=UTC))
            _insert(conn, superseded=datetime(2026, 2, 1, tzinfo=UTC))
            _insert(conn, superseded=None)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            _insert(conn, superseded=None)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO declared_input_values (tenant_id, company_id, input_key, base, unit, "
                    "status, method, metadata, created_at, updated_at) VALUES "
                    "(1, 1, 'x', 1, 'ratio', 'inventado', 'infer', '{}', '2026-01-01', '2026-01-01')"
                )
            )
        engine.dispose()

        command.downgrade(cfg, "0126_email_user_prefs")
        engine = sa.create_engine(url)
        assert TABLE not in sa.inspect(engine).get_table_names()
        engine.dispose()

        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        assert TABLE in sa.inspect(engine).get_table_names()
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_0127_modelo_declara_las_mismas_columnas_e_indices() -> None:
    from app.models import DeclaredInputValue

    table = DeclaredInputValue.__table__
    assert {c.name for c in table.columns} == COLUMNS
    assert {ix.name for ix in table.indexes} == INDEXES
    current = next(ix for ix in table.indexes if ix.name == "uq_declared_input_current")
    assert current.unique
    assert [c.name for c in current.columns] == ["tenant_id", "company_id", "input_key", "segment_key"]


def test_0127_round_trip_en_postgres() -> None:
    """Postgres real en un schema aislado (job de CI o PG local con CI=true)."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    schema = "dinputs_0127_" + uuid.uuid4().hex
    module = _module()
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.execute(sa.schema.CreateSchema(schema))
                conn.execute(sa.text("SELECT set_config('search_path', :schema, true)"), {"schema": schema})
                conn.execute(sa.text("CREATE TABLE tenants (id INTEGER PRIMARY KEY)"))
                conn.execute(sa.text("CREATE TABLE companies (id INTEGER PRIMARY KEY)"))
                conn.execute(sa.text("CREATE TABLE documents (id INTEGER PRIMARY KEY)"))
                conn.execute(sa.text("INSERT INTO tenants VALUES (1)"))
                conn.execute(sa.text("INSERT INTO companies VALUES (1)"))
                module.op = Operations(MigrationContext.configure(conn))
                module.upgrade()
                inspector = sa.inspect(conn)
                assert TABLE in inspector.get_table_names(schema=schema)
                assert {c["name"] for c in inspector.get_columns(TABLE, schema=schema)} == COLUMNS
                assert {ix["name"] for ix in inspector.get_indexes(TABLE, schema=schema)} >= INDEXES
                module.upgrade()  # idempotente
                _insert(conn, superseded=datetime(2026, 1, 1, tzinfo=UTC))
                _insert(conn, superseded=None)
                savepoint = conn.begin_nested()
                with pytest.raises(IntegrityError):
                    _insert(conn, superseded=None)
                savepoint.rollback()
                module.downgrade()
                assert TABLE not in sa.inspect(conn).get_table_names(schema=schema)
                module.upgrade()
                assert TABLE in sa.inspect(conn).get_table_names(schema=schema)
            finally:
                transaction.rollback()  # Solo borra el schema temporal de este test.
    finally:
        engine.dispose()
