"""0121: indice del feed de alertas del inicio.

sqlite: tras upgrade head el indice existe con tenant_id al frente.
Postgres (gated CI): reentrada sin recrear.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.test_alembic_chain import VERSIONS_DIR, _url_postgres_ci

_NOMBRE = "ix_research_alerts_home_feed"


def test_0121_indice_existe_tras_upgrade_head_en_sqlite(tmp_path) -> None:
    # En subproceso (patron de test_migrations.py): env.py hace fileConfig y
    # un command.upgrade en proceso tumba el logging (y caplog) del resto de
    # la suite. env.py lee get_settings().database_url, o sea DATABASE_URL.
    import os
    import subprocess
    import sys

    url = f"sqlite:///{tmp_path}/mig0121.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=VERSIONS_DIR.parent.parent,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-800:]
    # La reflexion de sqlite salta indices con expresiones: sqlite_master.
    engine = sa.create_engine(url)
    with engine.connect() as conn:
        ddl = conn.execute(
            sa.text("select sql from sqlite_master where type = 'index' and name = :n"),
            {"n": _NOMBRE},
        ).scalar()
    assert ddl is not None
    assert "tenant_id" in ddl
    assert "coalesce(last_triggered_at, created_at)" in ddl


def test_0121_reentrada_en_postgres() -> None:
    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = sa.create_engine(url)
    with engine.connect() as conn:
        oid_antes = conn.execute(
            sa.text(
                "select idx.oid from pg_class idx join pg_index i "
                "on i.indexrelid = idx.oid where idx.relname = :n and i.indisvalid"
            ),
            {"n": _NOMBRE},
        ).scalar()
    assert oid_antes is not None
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        oid_despues = conn.execute(
            sa.text("select oid from pg_class where relname = :n"), {"n": _NOMBRE}
        ).scalar()
    assert oid_antes == oid_despues
