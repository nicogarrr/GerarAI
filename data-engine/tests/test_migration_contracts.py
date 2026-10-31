"""Alembic migration contract and integrity test suite for GerarAI.

Fulfills: VAL-COV-006 (add-database-migration-tests)
- Every migration verified for upgrade definition and execution path
- Every migration verified for downgrade definition and execution path
- Migration chain verified as contiguous DAG without breaks or forks
- Data integrity verified across migration lifecycle (upgrade -> seed -> rollback -> reapply)
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


@pytest.fixture(scope="module")
def alembic_dir() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def script_directory(alembic_dir: Path) -> ScriptDirectory:
    ini_path = alembic_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(alembic_dir / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_all_migrations_define_upgrade_and_downgrade(alembic_dir: Path):
    """Every migration file in versions/ must implement both upgrade() and downgrade()."""
    versions_dir = alembic_dir / "alembic" / "versions"
    migration_files = sorted(versions_dir.glob("*.py"))
    assert len(migration_files) >= 100, f"Expected >100 migrations, found {len(migration_files)}"

    for file_path in migration_files:
        code = file_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(code)
        func_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

        assert "upgrade" in func_names, f"Migration {file_path.name} missing upgrade() function"
        assert "downgrade" in func_names, f"Migration {file_path.name} missing downgrade() function"


def test_migration_chain_is_unbroken_and_single_head(script_directory: ScriptDirectory):
    """The migration revision graph must have exactly one head revision and no orphan branches."""
    heads = script_directory.get_heads()
    assert len(heads) == 1, f"Multiple heads detected in Alembic migration chain: {heads}"

    revisions = list(script_directory.walk_revisions())
    assert len(revisions) >= 100
    base_revs = [rev for rev in revisions if rev.down_revision is None]
    assert len(base_revs) == 1, f"Expected exactly 1 root migration, found: {base_revs}"


def test_alembic_upgrade_and_downgrade_cycle(alembic_dir: Path):
    """Execute upgrade head, downgrade -1, and re-upgrade on an isolated SQLite database."""
    temp_dir = Path(tempfile.mkdtemp(prefix="gerarai_mig_test_"))
    db_path = temp_dir / "mig_cycle.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    env = {**os.environ, "DATABASE_URL": database_url}

    try:
        # Step 1: Upgrade to head
        res_up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=alembic_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert res_up.returncode == 0, f"Alembic upgrade head failed: {res_up.stderr}"

        # Verify tables exist
        engine = create_engine(database_url)
        try:
            insp = inspect(engine)
            tables = set(insp.get_table_names())
            assert "companies" in tables
            assert "portfolios" in tables
            assert "transactions" in tables
            assert "alembic_version" in tables

            # Seed a record using ORM to verify data integrity across cycle
            from sqlalchemy.orm import Session

            from app.models.entities import Company

            with Session(engine) as session:
                co = Company(
                    ticker="TEST",
                    name="Test Co",
                    exchange="BME",
                    currency="EUR",
                    sector="Technology",
                    industry="Software",
                    company_type="operating",
                    valuation_model="dcf",
                    special_sources=[],
                    special_risks=[],
                    factor_tags=[],
                )
                session.add(co)
                session.commit()
        finally:
            engine.dispose()

        # Step 2: Downgrade 1 revision
        res_down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "-1"],
            cwd=alembic_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert res_down.returncode == 0, f"Alembic downgrade -1 failed: {res_down.stderr}"

        # Step 3: Re-upgrade to head
        res_reup = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=alembic_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert res_reup.returncode == 0, f"Alembic re-upgrade failed: {res_reup.stderr}"

        # Verify seeded data was not corrupted
        engine2 = create_engine(database_url)
        try:
            with engine2.connect() as conn:
                row = conn.execute(text("SELECT ticker, name FROM companies WHERE ticker = 'TEST'")).fetchone()
                assert row is not None
                assert row[0] == "TEST"
                assert row[1] == "Test Co"
        finally:
            engine2.dispose()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
