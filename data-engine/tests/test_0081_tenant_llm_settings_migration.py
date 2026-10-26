"""0081 tenant_llm_settings: upgrade, downgrade y adopcion no destructiva."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from app.models.entities import TenantLLMSettings

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION = "0081_tenant_llm_settings"
DOWN_REVISION = "0080_privacy_audit_events"
TABLE = "tenant_llm_settings"
INDEX = "ix_tenant_llm_settings_tenant_id"


def _alembic(database_url: str, *args: str) -> None:
    result = _alembic_run(database_url, *args)
    assert result.returncode == 0, result.stderr


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


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _seed_row(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                TenantLLMSettings.__table__.insert().values(
                    id=1,
                    tenant_id=1,
                    provider="openai",
                    base_url=None,
                    model="gpt-4.1-mini",
                    fallback_model=None,
                    reasoning_effort="low",
                    api_key_ciphertext="v1:ciphertext",
                    api_key_last4="1234",
                    key_version=1,
                    enabled=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    finally:
        engine.dispose()


def _row_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql(f"SELECT COUNT(*) FROM {TABLE}").scalar_one()


def test_upgrade_creates_table_and_downgrade_drops_it(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "fresh.db")
    _alembic(database_url, "upgrade", REVISION)
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert TABLE in inspector.get_table_names()
        columns = {col["name"]: col for col in inspector.get_columns(TABLE)}
        assert columns["tenant_id"]["nullable"] is False
        unique = inspector.get_unique_constraints(TABLE)
        assert any(set(item["column_names"]) == {"tenant_id"} for item in unique)
        _seed_row(database_url)
        assert _row_count(engine) == 1
    finally:
        engine.dispose()

    _alembic(database_url, "downgrade", "-1")
    engine = create_engine(database_url)
    try:
        assert TABLE not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_upgrade_adopts_preexisting_table_and_downgrade_keeps_it(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "adopted.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        TenantLLMSettings.__table__.create(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {INDEX}")
    finally:
        engine.dispose()
    _seed_row(database_url)

    _alembic(database_url, "upgrade", REVISION)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert INDEX in {ix["name"] for ix in inspector.get_indexes(TABLE)}
        assert _row_count(engine) == 1
        with engine.connect() as conn:
            rows = list(
                conn.exec_driver_sql(
                    "SELECT revision, table_name, created_indexes"
                    " FROM migration_adoption_log"
                )
            )
        assert rows == [(REVISION, TABLE, INDEX)]
    finally:
        engine.dispose()

    _alembic(database_url, "downgrade", "-1")

    engine = create_engine(database_url)
    try:
        assert TABLE in inspect(engine).get_table_names()
        assert _row_count(engine) == 1
    finally:
        engine.dispose()


def test_upgrade_rejects_divergent_preexisting_table(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "divergent.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                f"""
                CREATE TABLE {TABLE} (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL UNIQUE,
                    provider VARCHAR(10) NOT NULL,
                    base_url VARCHAR(500),
                    model VARCHAR(200) NOT NULL,
                    fallback_model VARCHAR(200),
                    reasoning_effort VARCHAR(20),
                    api_key_ciphertext TEXT,
                    api_key_last4 VARCHAR(8),
                    key_version INTEGER NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
    finally:
        engine.dispose()

    result = _alembic_run(database_url, "upgrade", REVISION)

    assert result.returncode != 0
    assert "NO coincide" in result.stderr
    assert "provider" in result.stderr
