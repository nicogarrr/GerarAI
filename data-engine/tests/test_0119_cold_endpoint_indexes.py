"""0119: indices de endpoints en frio presentes, validos, parciales y reentrantes.

Corre en el job 'Postgres migration round trip' sobre una BD scratch
desechable migrada a head. En sqlite/local hace skip. Replica el patron del
gate de 0117 (misma clase de migracion: CREATE INDEX CONCURRENTLY con
autocommit_block).
"""

import os

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.core.config import get_settings
from tests.test_0114_fk_ondelete import _scratch
from tests.test_alembic_chain import VERSIONS_DIR, _url_postgres_ci

_NOMBRES = ["ix_calc_metrics_tenant_metric_ok", "ix_market_prices_source_cov"]

_ESTADO = (
    "select idx.relname, i.indisvalid, i.indisready, pg_get_expr(i.indpred, i.indrelid) "
    "from pg_index i join pg_class idx on idx.oid = i.indexrelid "
    "join pg_class t on t.oid = i.indrelid "
    "join pg_namespace n on n.oid = t.relnamespace "
    "where n.nspname = current_schema() and idx.relname = any(:nombres)"
)

_OIDS = (
    "select idx.relname, i.indexrelid "
    "from pg_index i join pg_class idx on idx.oid = i.indexrelid "
    "join pg_class t on t.oid = i.indrelid "
    "join pg_namespace n on n.oid = t.relnamespace "
    "where n.nspname = current_schema() and idx.relname = any(:nombres)"
)


def _alembic(scratch_url: str, fn, revision: str) -> None:
    anterior = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = scratch_url
    get_settings.cache_clear()
    try:
        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        fn(cfg, revision)
    finally:
        if anterior:
            os.environ["DATABASE_URL"] = anterior
        else:
            os.environ.pop("DATABASE_URL", None)
        get_settings.cache_clear()


def test_0119_indices_validos_parciales_y_reentrantes_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo corre en el job de CI con Postgres")

    scratch, scratch_url, admin = _scratch(url)
    engine = sa.create_engine(scratch_url)
    try:
        with engine.connect() as conn:
            estado = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
                sa.text(_ESTADO), {"nombres": _NOMBRES})}
        assert set(estado) == set(_NOMBRES), estado
        assert all(v and r for v, r, _ in estado.values()), estado
        # predicados parciales tal y como los filtran las consultas
        assert estado["ix_market_prices_source_cov"][2] .strip("()") == "close > (0)::numeric"
        assert "'ok'" in estado["ix_calc_metrics_tenant_metric_ok"][2]
        assert "IS NOT NULL" in estado["ix_calc_metrics_tenant_metric_ok"][2]

        # INVALID homonimo en OTRO schema: no se toca
        with engine.begin() as conn:
            conn.execute(sa.text("create schema if not exists ajeno0119"))
            conn.execute(sa.text(
                "create table ajeno0119.market_prices ("
                "source text, company_id int, updated_at timestamptz, close numeric)"))
            conn.execute(sa.text(
                "create index ix_market_prices_source_cov "
                "on ajeno0119.market_prices (source, company_id, updated_at)"))
            conn.execute(sa.text(
                "update pg_index set indisvalid = false "
                "where indexrelid = 'ajeno0119.ix_market_prices_source_cov'::regclass"))

        # reentrada real: stamp a 0118 con los 2 validos y upgrade de nuevo
        with engine.connect() as conn:
            oids_antes = dict(conn.execute(sa.text(_OIDS), {"nombres": _NOMBRES}).all())
        assert set(oids_antes) == set(_NOMBRES)
        _alembic(scratch_url, command.stamp, "0118_thesis_attention_idx")
        _alembic(scratch_url, command.upgrade, "head")
        with engine.connect() as conn:
            oids_despues = dict(conn.execute(sa.text(_OIDS), {"nombres": _NOMBRES}).all())
            ajeno = conn.execute(sa.text(
                "select i.indisvalid from pg_index i "
                "where i.indexrelid = 'ajeno0119.ix_market_prices_source_cov'::regclass"
            )).scalar_one()
        assert oids_despues == oids_antes, "recreo indices ya validos"
        assert ajeno is False, "el INVALID de otro schema se toco"
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- fixture: nombre uuid-hex generado por _scratch (test_0114), sin input externo; BD efimera de CI
