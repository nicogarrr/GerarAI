"""0086 decision_journal_entries.transaction_id: upgrade con FK SET NULL, downgrade limpio."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION = "0086_journal_transaction_link"
DOWN_REVISION = "0082_financial_facts_filed"
TABLE = "decision_journal_entries"


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


def _inspect(database_url: str) -> tuple[set[str], list, set[str]]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns(TABLE)}
        fks = inspector.get_foreign_keys(TABLE)
        indexes = {str(ix["name"]) for ix in inspector.get_indexes(TABLE)}
        return columns, fks, indexes
    finally:
        engine.dispose()


def test_upgrade_adds_fk_column_and_downgrade_removes_it(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    _alembic(database_url, "upgrade", DOWN_REVISION)
    columns, _fks, _ = _inspect(database_url)
    assert "transaction_id" not in columns

    _alembic(database_url, "upgrade", REVISION)
    columns, fks, indexes = _inspect(database_url)
    assert "transaction_id" in columns
    fk = next(item for item in fks if item["constrained_columns"] == ["transaction_id"])
    assert fk["referred_table"] == "transactions"
    assert (fk.get("options") or {}).get("ondelete") == "SET NULL"
    assert "ix_decision_journal_entries_transaction_id" in indexes
    # Las columnas de siempre siguen ahi.
    assert {"decision", "rationale", "price", "thesis_version_id"} <= columns

    _alembic(database_url, "downgrade", DOWN_REVISION)
    columns, fks, _ = _inspect(database_url)
    assert "transaction_id" not in columns
    assert not any(item["constrained_columns"] == ["transaction_id"] for item in fks)
