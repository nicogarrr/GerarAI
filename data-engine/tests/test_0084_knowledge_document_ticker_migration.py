"""0084 knowledge_documents.ticker: upgrade, downgrade e idempotencia."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION = "0084_knowledge_document_ticker"
DOWN_REVISION = "0082_financial_facts_filed"
TABLE = "knowledge_documents"
INDEX = "ix_knowledge_documents_ticker"


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


def _columns_and_indexes(database_url: str) -> tuple[dict, set[str]]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {col["name"]: col for col in inspector.get_columns(TABLE)}
        indexes = {ix["name"] for ix in inspector.get_indexes(TABLE)}
        return columns, indexes
    finally:
        engine.dispose()


def test_upgrade_anade_ticker_nullable_indexado_y_downgrade_lo_quita(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    _alembic(database_url, "upgrade", DOWN_REVISION)
    columns, _ = _columns_and_indexes(database_url)
    assert "ticker" not in columns

    _alembic(database_url, "upgrade", REVISION)
    columns, indexes = _columns_and_indexes(database_url)
    assert columns["ticker"]["nullable"] is True
    assert INDEX in indexes

    _alembic(database_url, "downgrade", DOWN_REVISION)
    columns, indexes = _columns_and_indexes(database_url)
    assert "ticker" not in columns
    assert INDEX not in indexes


def test_upgrade_es_idempotente_si_la_columna_ya_existe(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'adopted.db').as_posix()}"
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN ticker VARCHAR(32)")
    finally:
        engine.dispose()

    _alembic(database_url, "upgrade", REVISION)
    columns, indexes = _columns_and_indexes(database_url)
    assert "ticker" in columns
    assert INDEX in indexes
