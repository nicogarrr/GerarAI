import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect

POSTGRESQL_MAX_IDENTIFIER_LENGTH = 63


def test_alembic_upgrade_head_creates_research_memory_tables():
    data_engine_dir = Path(__file__).resolve().parents[1]
    temp_dir = Path(tempfile.mkdtemp(prefix="cavaai_migration_"))
    database_url = f"sqlite:///{(temp_dir / 'migration.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": database_url}

    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=data_engine_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )

        assert result.returncode == 0, result.stderr

        engine = create_engine(database_url)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())
            schema_identifiers = set(tables)
            for table in tables:
                for index in inspector.get_indexes(table):
                    if index_name := index.get("name"):
                        schema_identifiers.add(index_name)
                for constraint in inspector.get_unique_constraints(table):
                    if constraint_name := constraint.get("name"):
                        schema_identifiers.add(constraint_name)
                for foreign_key in inspector.get_foreign_keys(table):
                    if foreign_key_name := foreign_key.get("name"):
                        schema_identifiers.add(foreign_key_name)
        finally:
            engine.dispose()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert {
        "claims",
        "claim_evidence",
        "thesis_sections",
        "thesis_changes",
        "research_sessions",
        "memory_items",
        "calculated_metrics",
        "fundamental_model_versions",
        "fundamental_drivers",
        "fundamental_assumptions",
        "fundamental_forecasts",
        "decision_journal_entries",
        "expectation_reviews",
        "model_aliases",
    }.issubset(tables)
    assert not {
        identifier
        for identifier in schema_identifiers
        if len(identifier) > POSTGRESQL_MAX_IDENTIFIER_LENGTH
    }, "Committed migrations contain identifiers PostgreSQL cannot create"


def test_latest_fundamental_migration_is_explicit_and_not_metadata_driven():
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0006_fundamental_model_journal.py"
    ).read_text(encoding="utf-8")

    assert "Base.metadata" not in migration
    assert "op.create_table" in migration
    assert "fundamental_model_versions" in migration
    assert "decision_journal_entries" in migration


def _executable_code(source: str) -> str:
    """Devuelve el codigo sin comentarios y con docstrings vaciados.

    El guard de migraciones congeladas debe inspeccionar codigo, no prosa:
    un docstring que mencione "Base.metadata" (p.ej. describiendo como se
    midio la reconciliacion) no es una importacion de metadata mutable.
    """
    tree = ast.parse(source.lstrip("\ufeff"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                first.value.value = ""
    return ast.unparse(tree)


def test_every_committed_migration_is_frozen_and_explicit():
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"

    for path in sorted(versions.glob("*.py")):
        migration = _executable_code(path.read_text(encoding="utf-8"))
        assert "Base.metadata" not in migration, f"{path.name} imports mutable ORM metadata"
        assert "metadata.create_all" not in migration, f"{path.name} creates the current schema dynamically"
