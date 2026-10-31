"""0120: indices de lectura del feed de news y del screener.

Dos capas:

1. sqlite (toda la suite): tras migrar a head, los tres indices existen con
   sus columnas; la variante sqlite del indice de la ventana usa DESC plano
   (sqlite no acepta NULLS LAST en CREATE INDEX) y los parciales llevan su
   sqlite_where.
2. Postgres (gated al job CI): reentrada real sobre PG — upgrade con los
   indices ya validos no recrea ni falla, downgrade/upgrade restaura.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.test_alembic_chain import VERSIONS_DIR, _url_postgres_ci

_NOMBRES = {
    "ix_news_events_date_id": "news_events",
    "ix_news_events_macro_date_id": "news_events",
    "ix_calc_metrics_screener_window": "calculated_metrics",
}


def _sqlite_head(tmp_path, monkeypatch) -> sa.Engine:
    # env.py lee get_settings().database_url, no el sqlalchemy.url del cfg.

    from app.core.config import get_settings

    url = f"sqlite:///{tmp_path}/mig0120.db"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    command.upgrade(cfg, "head")
    get_settings.cache_clear()
    return sa.create_engine(url)


def test_0120_indices_existen_tras_upgrade_head_en_sqlite(tmp_path, monkeypatch) -> None:
    engine = _sqlite_head(tmp_path, monkeypatch)
    with engine.connect() as conn:
        encontrados = {
            ix["name"]
            for tabla in set(_NOMBRES.values())
            for ix in sa.inspect(conn).get_indexes(tabla)
        }
    assert set(_NOMBRES) <= encontrados


def test_0120_ventana_screener_cubre_particion_y_orden_en_sqlite(tmp_path, monkeypatch) -> None:
    engine = _sqlite_head(tmp_path, monkeypatch)
    with engine.connect() as conn:
        ix = next(
            item
            for item in sa.inspect(conn).get_indexes("calculated_metrics")
            if item["name"] == "ix_calc_metrics_screener_window"
        )
    assert ix["column_names"][:3] == ["tenant_id", "company_id", "metric"]


def test_0120_reentrada_en_postgres() -> None:
    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    # env.py fuerza sqlalchemy.url = get_settings().database_url (lee
    # DATABASE_URL), asi que set_main_option("sqlalchemy.url", ...) no hace
    # nada: hay que pasar la URL por entorno. En subproceso, como el test de
    # sqlite de este archivo: env.py hace fileConfig y un upgrade en proceso
    # tumba el logging del resto de la suite.
    import os
    import subprocess
    import sys

    env = {**os.environ, "CI": "true", "DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=VERSIONS_DIR.parent.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-800:]
    engine = sa.create_engine(url)
    with engine.connect() as conn:
        oids_antes = {
            row[0]: row[1]
            for row in conn.execute(
                sa.text(
                    "select idx.relname, idx.oid from pg_class idx "
                    "join pg_index i on i.indexrelid = idx.oid "
                    "where idx.relname = any(:nombres) and i.indisvalid"
                ),
                {"nombres": list(_NOMBRES)},
            )
        }
    assert set(oids_antes) == set(_NOMBRES)
    # Reentrada: upgrade sobre head ya migrado no recrea (oids estables).
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=VERSIONS_DIR.parent.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-800:]
    with engine.connect() as conn:
        oids_despues = {
            row[0]: row[1]
            for row in conn.execute(
                sa.text(
                    "select idx.relname, idx.oid from pg_class idx "
                    "where idx.relname = any(:nombres)"
                ),
                {"nombres": list(_NOMBRES)},
            )
        }
    assert oids_antes == oids_despues
