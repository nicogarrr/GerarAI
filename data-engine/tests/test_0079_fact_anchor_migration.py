"""Paridad modelo <-> migracion 0079 fact_anchors, cadena y round trip.

El hallazgo de auditoria era que `FactAnchor` existia en el ORM sin migracion:
una base creada solo por Alembic no tenia `fact_anchors`. Este test aplica
`alembic upgrade head` sobre una SQLite temporal (patron de test_migrations) y
compara columnas, nullability, tipos, indices, unique y FKs contra el modelo.
Tambien exige que 0079 encadene con 0078 y pertenezca al head unico, y que downgrade -1
elimine la tabla y un upgrade posterior la recree.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import UniqueConstraint, create_engine, inspect
from sqlalchemy.engine import Engine

from app.models.entities import FactAnchor

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION = "0079_fact_anchors"
DOWN_REVISION = "0078_position_valuation_hold"


def _alembic(database_url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=DATA_ENGINE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _alembic_run(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=DATA_ENGINE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _seed_anchor_row(database_url: str) -> None:
    """Una fila preexistente: ni la adopcion ni el downgrade deben perderla."""
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                FactAnchor.__table__.insert().values(
                    id=1,
                    accession_number="0000320193-26-000001",
                    filename="aapl-20251231.htm",
                    body_sha256="a" * 64,
                    field="revenue",
                    value_text="100",
                    label="EXTRAIDO",
                    quote="revenue was 100",
                    quote_offset=12,
                    extractor="pytest",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    finally:
        engine.dispose()


def _anchor_row_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql("SELECT COUNT(*) FROM fact_anchors").scalar_one()


def _adoption_rows(engine: Engine) -> list[tuple[str, str, str]]:
    inspector = inspect(engine)
    if "migration_adoption_log" not in inspector.get_table_names():
        return []
    with engine.connect() as conn:
        return list(
            conn.exec_driver_sql("SELECT revision, table_name, created_indexes FROM migration_adoption_log")
        )


@pytest.fixture()
def migrated_engine(tmp_path: Path) -> Iterator[Engine]:
    database_url = _sqlite_url(tmp_path / "fact_anchors.db")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_migrated_fact_anchors_matches_model(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    dialect = migrated_engine.dialect

    migrated_columns = {col["name"]: col for col in inspector.get_columns("fact_anchors")}
    model_columns = {col.name: col for col in FactAnchor.__table__.columns}
    assert set(migrated_columns) == set(model_columns)
    for name, model_column in model_columns.items():
        migrated_column = migrated_columns[name]
        assert migrated_column["nullable"] == model_column.nullable, f"nullability de {name}"
        assert migrated_column["type"].compile(dialect=dialect) == model_column.type.compile(
            dialect=dialect
        ), f"tipo de {name}"

    assert inspector.get_pk_constraint("fact_anchors")["constrained_columns"] == ["id"]

    migrated_indexes = {
        index["name"]: (tuple(index["column_names"]), bool(index["unique"]))
        for index in inspector.get_indexes("fact_anchors")
    }
    model_indexes = {
        index.name: (tuple(col.name for col in index.columns), bool(index.unique))
        for index in FactAnchor.__table__.indexes
    }
    assert migrated_indexes == model_indexes

    migrated_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("fact_anchors")
    }
    model_uniques = {
        constraint.name: tuple(col.name for col in constraint.columns)
        for constraint in FactAnchor.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert migrated_uniques == model_uniques

    migrated_fks = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            fk.get("options", {}).get("ondelete"),
        )
        for fk in inspector.get_foreign_keys("fact_anchors")
    }
    model_fks = {
        ((fk.parent.name,), fk.column.table.name, (fk.column.name,), fk.ondelete)
        for fk in FactAnchor.__table__.foreign_keys
    }
    assert migrated_fks == model_fks


def test_0079_chains_to_0078_and_belongs_to_the_single_head() -> None:
    """No fija el head a 0079: futuras migraciones (0080+) deben poder
    añadirse sin editar este test. La invariante de un solo head ya la cubre
    `test_alembic_chain.py`."""
    script = ScriptDirectory(str(DATA_ENGINE_DIR / "alembic"))
    heads = script.get_heads()
    assert len(heads) == 1
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    ancestry = {item.revision for item in script.iterate_revisions(heads[0], "base")}
    assert REVISION in ancestry


def test_0079_downgrade_drops_table_and_upgrade_recreates_it(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "fact_anchors_roundtrip.db")

    _alembic(database_url, "upgrade", REVISION)
    _alembic(database_url, "downgrade", "-1")
    engine = create_engine(database_url)
    try:
        assert "fact_anchors" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        assert "fact_anchors" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_upgrade_adopts_compatible_preexisting_table(tmp_path: Path) -> None:
    """Prod: init_db() creo fact_anchors via create_all antes de llegar Alembic.

    La adopcion valida el esquema completo contra la definicion congelada,
    crea solo los indices que falten y registra la adopcion sin perder filas.
    """
    database_url = _sqlite_url(tmp_path / "preexisting.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        FactAnchor.__table__.create(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP INDEX IF EXISTS ix_fact_anchors_company")
    finally:
        engine.dispose()
    _seed_anchor_row(database_url)

    _alembic(database_url, "upgrade", REVISION)

    engine = create_engine(database_url)
    try:
        names = {ix["name"] for ix in inspect(engine).get_indexes("fact_anchors")}
        assert {
            "ix_fact_anchors_tenant_id",
            "ix_fact_anchors_accession_number",
            "ix_fact_anchors_company",
        } <= names
        assert _anchor_row_count(engine) == 1
        assert _adoption_rows(engine) == [(REVISION, "fact_anchors", "ix_fact_anchors_company")]
    finally:
        engine.dispose()


def test_upgrade_rejects_divergent_preexisting_table(tmp_path: Path) -> None:
    """Una tabla con el mismo nombre pero esquema distinto NO se adopta.

    La migracion debe fallar nombrando cada divergencia y dejar la tabla
    exactamente como estaba (origen no confirmado: reconciliacion manual).
    """
    database_url = _sqlite_url(tmp_path / "divergent.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            # DDL independiente del modelo: tipo distinto en body_sha256 y sin
            # la restriccion UNIQUE de 6 columnas.
            conn.exec_driver_sql(
                """
                CREATE TABLE fact_anchors (
                    id INTEGER NOT NULL PRIMARY KEY,
                    accession_number VARCHAR(40) NOT NULL,
                    filename VARCHAR(255) NOT NULL,
                    body_sha256 VARCHAR(32) NOT NULL,
                    field VARCHAR(80) NOT NULL,
                    value_text VARCHAR(2000) NOT NULL,
                    label VARCHAR(10) NOT NULL,
                    quote TEXT NOT NULL,
                    quote_offset INTEGER NOT NULL,
                    item VARCHAR(40),
                    extractor VARCHAR(120) NOT NULL,
                    derivation TEXT,
                    company_id INTEGER,
                    tenant_id INTEGER,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(company_id) REFERENCES companies (id),
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                )
                """
            )
    finally:
        engine.dispose()

    result = _alembic_run(database_url, "upgrade", REVISION)

    assert result.returncode != 0
    assert "no se adopta" in result.stderr
    assert "body_sha256" in result.stderr
    assert "UNIQUE" in result.stderr
    engine = create_engine(database_url)
    try:
        columns = {col["name"]: col for col in inspect(engine).get_columns("fact_anchors")}
        assert columns["body_sha256"]["type"].compile(dialect=engine.dialect) == "VARCHAR(32)"
        assert inspect(engine).get_unique_constraints("fact_anchors") == []
        assert _adoption_rows(engine) == []
    finally:
        engine.dispose()


def test_downgrade_keeps_adopted_table_and_its_rows(tmp_path: Path) -> None:
    """Si 0079 adopto la tabla, downgrade NO la destruye.

    Solo retira lo que la adopcion anadio y el registro; una tabla creada por
    la propia migracion sigue eliminandose entera (test del round trip).
    """
    database_url = _sqlite_url(tmp_path / "adopted_downgrade.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        FactAnchor.__table__.create(engine)
    finally:
        engine.dispose()
    _seed_anchor_row(database_url)
    _alembic(database_url, "upgrade", REVISION)

    _alembic(database_url, "downgrade", "-1")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "fact_anchors" in inspector.get_table_names()
        assert _anchor_row_count(engine) == 1
        names = {ix["name"] for ix in inspector.get_indexes("fact_anchors")}
        assert {
            "ix_fact_anchors_tenant_id",
            "ix_fact_anchors_accession_number",
            "ix_fact_anchors_company",
        } <= names
        assert "migration_adoption_log" not in inspector.get_table_names()
    finally:
        engine.dispose()

    # Re-upgrade tras el downgrade: la adopcion es repetible.
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        assert "fact_anchors" in inspect(engine).get_table_names()
        assert _anchor_row_count(engine) == 1
        assert _adoption_rows(engine) == [(REVISION, "fact_anchors", "")]
    finally:
        engine.dispose()
