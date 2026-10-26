"""Adopcion no destructiva de 0080 privacy_audit_events.

Misma regresion que 0079: `init_db()` ejecuta `Base.metadata.create_all` en
cada arranque del backend, asi que la tabla puede existir antes de que
Alembic llegue a 0080. La migracion debe adoptarla solo si el esquema
reflejado coincide por completo, fallar con las divergencias si no, y su
downgrade no debe destruir una tabla preexistente.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from app.models.entities import PrivacyAuditEvent

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION = "0080_privacy_audit_events"
DOWN_REVISION = "0079_fact_anchors"


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


def _seed_event_row(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                PrivacyAuditEvent.__table__.insert().values(
                    id=1,
                    event_type="account.delete",
                    tenant_external_id="t-1",
                    user_id="u-1",
                    detail={"k": "v"},
                    created_at=datetime.now(UTC),
                )
            )
    finally:
        engine.dispose()


def _event_row_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql("SELECT COUNT(*) FROM privacy_audit_events").scalar_one()


def test_upgrade_adopts_compatible_preexisting_table(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "preexisting.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        PrivacyAuditEvent.__table__.create(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP INDEX IF EXISTS ix_privacy_audit_events_user_id")
    finally:
        engine.dispose()
    _seed_event_row(database_url)

    _alembic(database_url, "upgrade", REVISION)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        names = {ix["name"] for ix in inspector.get_indexes("privacy_audit_events")}
        assert {
            "ix_privacy_audit_events_event_type",
            "ix_privacy_audit_events_tenant_external_id",
            "ix_privacy_audit_events_user_id",
            "ix_privacy_audit_events_created_at",
        } <= names
        assert _event_row_count(engine) == 1
        doc_columns = {col["name"] for col in inspector.get_columns("documents")}
        assert "retention_tombstoned_at" in doc_columns
        with engine.connect() as conn:
            rows = list(conn.exec_driver_sql("SELECT revision, created_indexes FROM migration_adoption_log"))
        assert rows == [(REVISION, "doccol,docidx,idx:ix_privacy_audit_events_user_id")]
    finally:
        engine.dispose()


def test_upgrade_rejects_divergent_preexisting_table(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "divergent.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            # DDL independiente del modelo: tipo distinto en event_type.
            conn.exec_driver_sql(
                """
                CREATE TABLE privacy_audit_events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    event_type VARCHAR(30) NOT NULL,
                    tenant_external_id VARCHAR(160),
                    user_id VARCHAR(160),
                    detail JSON NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
    finally:
        engine.dispose()

    result = _alembic_run(database_url, "upgrade", REVISION)

    assert result.returncode != 0
    assert "no se adopta" in result.stderr
    assert "event_type" in result.stderr
    engine = create_engine(database_url)
    try:
        columns = {col["name"]: col for col in inspect(engine).get_columns("privacy_audit_events")}
        assert columns["event_type"]["type"].compile(dialect=engine.dialect) == "VARCHAR(30)"
        doc_columns = {col["name"] for col in inspect(engine).get_columns("documents")}
        assert "retention_tombstoned_at" not in doc_columns
    finally:
        engine.dispose()


def test_downgrade_keeps_adopted_table_and_its_rows(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path / "adopted_downgrade.db")
    _alembic(database_url, "upgrade", DOWN_REVISION)
    engine = create_engine(database_url)
    try:
        PrivacyAuditEvent.__table__.create(engine)
    finally:
        engine.dispose()
    _seed_event_row(database_url)
    _alembic(database_url, "upgrade", REVISION)

    _alembic(database_url, "downgrade", "-1")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "privacy_audit_events" in inspector.get_table_names()
        assert _event_row_count(engine) == 1
        doc_columns = {col["name"] for col in inspector.get_columns("documents")}
        assert "retention_tombstoned_at" not in doc_columns
        assert "migration_adoption_log" not in inspector.get_table_names()
    finally:
        engine.dispose()

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        assert "privacy_audit_events" in inspect(engine).get_table_names()
        assert _event_row_count(engine) == 1
    finally:
        engine.dispose()
