"""0083 dca_signal_states/dca_alert_overrides: alta, adopcion y downgrade."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.models.entities import DcaAlertOverride, DcaSignalState

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION = "0083_dca_signal_states"
DOWN_REVISION = "0082_financial_facts_filed"


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=DATA_ENGINE_DIR, env=env, capture_output=True, text=True, timeout=180,
    )


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_and_downgrade_drops(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    assert _alembic(url, "upgrade", REVISION).returncode == 0
    tables = _tables(url)
    assert {"dca_signal_states", "dca_alert_overrides"} <= tables
    engine = create_engine(url)
    try:
        uniques = inspect(engine).get_unique_constraints("dca_signal_states")
        assert any(tuple(u["column_names"]) == ("tenant_id", "symbol") for u in uniques)
    finally:
        engine.dispose()
    result = _alembic(url, "downgrade", DOWN_REVISION)
    assert result.returncode == 0, result.stderr
    assert not ({"dca_signal_states", "dca_alert_overrides"} & _tables(url))


def test_upgrade_adopts_tables_created_by_orm(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'adopt.db').as_posix()}"
    assert _alembic(url, "upgrade", DOWN_REVISION).returncode == 0
    engine = create_engine(url)
    try:
        DcaSignalState.__table__.create(engine)
        DcaAlertOverride.__table__.create(engine)
    finally:
        engine.dispose()
    result = _alembic(url, "upgrade", REVISION)
    assert result.returncode == 0, result.stderr
    result = _alembic(url, "downgrade", DOWN_REVISION)
    assert result.returncode == 0, result.stderr
    # Adoptadas: el downgrade no las borra.
    assert {"dca_signal_states", "dca_alert_overrides"} <= _tables(url)


def test_upgrade_refuses_divergent_preexisting_table(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'bad.db').as_posix()}"
    assert _alembic(url, "upgrade", DOWN_REVISION).returncode == 0
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE dca_alert_overrides (id INTEGER PRIMARY KEY, symbol VARCHAR(20))")
    finally:
        engine.dispose()
    result = _alembic(url, "upgrade", REVISION)
    assert result.returncode != 0
    assert "Divergencias" in result.stderr
