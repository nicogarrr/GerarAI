"""0130: tabla ``analyst_notes`` (notas de analista estructuradas con su fuente).

Feature aprobada por Nico (4-nov-2026). Ciclo upgrade/downgrade/upgrade en sqlite
y en Postgres (job de CI o PG local con ``CI=true``), modelo y migración con las
mismas columnas, índices y listas, y unicidad de ``dedupe_key``.
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

TABLE = "analyst_notes"
REVISION = "0130_analyst_notes"
PREVIOUS = "0129_value_drivers"
COLUMNS = {
    "id",
    "tenant_id",
    "company_id",
    "ticker",
    "firm",
    "firm_key",
    "analyst",
    "note_date",
    "action",
    "rating_old",
    "rating_new",
    "pt_old",
    "pt_new",
    "currency",
    "price_at_note",
    "key_arguments",
    "sentiment",
    "quote",
    "source_url",
    "source_type",
    "verification",
    "document_id",
    "estimates",
    "valuation",
    "segment_assumptions",
    "bull_target",
    "bear_target",
    "bull_case",
    "bear_case",
    "catalysts",
    "risks",
    "changes_since_previous",
    "links",
    "extras",
    "driver_refs",
    "dedupe_key",
    "created_at",
    "updated_at",
}
INDEXES = {"ix_analyst_notes_tenant_id", "ix_analyst_notes_company_id", "ix_analyst_notes_ticker"}


def _cfg(url: str, monkeypatch) -> Config:
    from app.core.config import get_settings

    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    return cfg


def _module():
    spec = importlib.util.spec_from_file_location("migration0130", VERSIONS_DIR / f"{REVISION}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _insert(conn, *, key: str = "k1", action: str = "upgrade") -> None:
    now = datetime.now(UTC)
    conn.execute(
        sa.text(
            "INSERT INTO analyst_notes (tenant_id, ticker, firm, firm_key, note_date, action, "
            "key_arguments, source_type, verification, estimates, valuation, segment_assumptions, "
            "catalysts, risks, links, extras, dedupe_key, created_at, updated_at) VALUES "
            "(1, 'PLTR', 'BofA', 'bofa', '2026-11-04', :action, '[]', 'news', 'fragmento', '{}', "
            "'{}', '{}', '[]', '[]', '[]', '{}', :key, :now, :now)"
        ),
        {"key": key, "action": action, "now": now},
    )


def test_0130_es_el_siguiente_al_head_anterior() -> None:
    module = _module()
    assert module.revision == REVISION
    assert module.down_revision == PREVIOUS
    assert len(module.revision) <= 32


def test_0130_upgrade_downgrade_upgrade_en_sqlite(tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    url = f"sqlite:///{tmp_path}/mig0130.db"
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
            _insert(conn)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            _insert(conn)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            _insert(conn, key="k2", action="inventada")
        engine.dispose()

        command.downgrade(cfg, PREVIOUS)
        engine = sa.create_engine(url)
        assert TABLE not in sa.inspect(engine).get_table_names()
        assert "value_drivers" in sa.inspect(engine).get_table_names()
        engine.dispose()

        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        assert TABLE in sa.inspect(engine).get_table_names()
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_0130_modelo_declara_las_mismas_columnas_e_indices() -> None:
    from app.models import AnalystNote

    table = AnalystNote.__table__
    assert {c.name for c in table.columns} == COLUMNS
    assert {ix.name for ix in table.indexes} == INDEXES
    assert table.c.driver_refs.nullable


def test_0130_listas_de_la_migracion_y_del_modelo_coinciden() -> None:
    from app.models import analyst_note as m

    module = _module()
    assert module.ACTIONS == m.ANALYST_NOTE_ACTIONS
    assert module.SOURCE_TYPES == m.ANALYST_NOTE_SOURCE_TYPES
    assert module.SENTIMENTS == m.ANALYST_NOTE_SENTIMENTS
    assert module.VERIFICATIONS == m.ANALYST_NOTE_VERIFICATIONS


def test_0130_round_trip_en_postgres() -> None:
    """Postgres real en un schema aislado (job de CI o PG local con CI=true)."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    schema = "anotes_0130_" + uuid.uuid4().hex
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
                module.op = Operations(MigrationContext.configure(conn))
                module.upgrade()
                inspector = sa.inspect(conn)
                assert TABLE in inspector.get_table_names(schema=schema)
                assert {c["name"] for c in inspector.get_columns(TABLE, schema=schema)} == COLUMNS
                assert {ix["name"] for ix in inspector.get_indexes(TABLE, schema=schema)} >= INDEXES
                module.upgrade()  # idempotente
                _insert(conn)
                savepoint = conn.begin_nested()
                with pytest.raises(IntegrityError):
                    _insert(conn)
                savepoint.rollback()
                savepoint = conn.begin_nested()
                with pytest.raises(IntegrityError):
                    _insert(conn, key="k2", action="inventada")
                savepoint.rollback()
                module.downgrade()
                assert TABLE not in sa.inspect(conn).get_table_names(schema=schema)
                module.upgrade()
                assert TABLE in sa.inspect(conn).get_table_names(schema=schema)
            finally:
                transaction.rollback()  # Solo borra el schema temporal de este test.
    finally:
        engine.dispose()
