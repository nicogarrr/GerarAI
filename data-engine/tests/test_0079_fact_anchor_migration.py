"""Paridad modelo <-> migracion 0079 fact_anchors, cadena y round trip.

El hallazgo de auditoria era que `FactAnchor` existia en el ORM sin migracion:
una base creada solo por Alembic no tenia `fact_anchors`. Este test aplica
`alembic upgrade head` sobre una SQLite temporal (patron de test_migrations) y
compara columnas, nullability, tipos, indices, unique y FKs contra el modelo.
Tambien exige que 0079 sea el unico head, encadene con 0078 y que downgrade -1
elimine la tabla y un upgrade posterior la recree.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
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
        assert (
            migrated_column["type"].compile(dialect=dialect)
            == model_column.type.compile(dialect=dialect)
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


def test_0079_is_the_single_head_and_chains_to_0078() -> None:
    script = ScriptDirectory(str(DATA_ENGINE_DIR / "alembic"))
    assert script.get_heads() == [REVISION]
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION


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
