"""0085 thesis_versions.invalidation_rules: upgrade anade la columna, downgrade la quita."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION = "0085_thesis_invalidation_rules"
DOWN_REVISION = "0084_knowledge_document_ticker"


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


def _columns(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url)
    try:
        return {col["name"]: col for col in inspect(engine).get_columns("thesis_versions")}
    finally:
        engine.dispose()


def test_upgrade_adds_nullable_column_and_downgrade_removes_it(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    _alembic(database_url, "upgrade", DOWN_REVISION)
    assert "invalidation_rules" not in _columns(database_url)

    _alembic(database_url, "upgrade", REVISION)
    columns = _columns(database_url)
    assert "invalidation_rules" in columns
    assert columns["invalidation_rules"]["nullable"] is True
    # El texto libre de siempre sigue ahi.
    assert "invalidation_criteria" in columns

    _alembic(database_url, "downgrade", DOWN_REVISION)
    assert "invalidation_rules" not in _columns(database_url)
