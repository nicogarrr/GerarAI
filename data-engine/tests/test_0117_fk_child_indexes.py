"""0117: CREATE INDEX CONCURRENTLY, repara INVALID propios, no toca ajenos.

Gated al job Postgres. Un intento CONCURRENTLY interrumpido deja el indice
con indisvalid = false; IF NOT EXISTS lo saltaria y quedaria inservible.
0117 lo detecta POR TABLA y schema efectivo (indrelid via search_path), lo
borra con DROP INDEX CONCURRENTLY y lo recrea. Un indice INVALID homonimo
de OTRO schema no se toca. La reentrada se prueba de verdad: stamp a 0116
con los 9 indices ya validos y upgrade de nuevo; los oids no cambian (no
recrea) y no falla.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.core.config import get_settings
from tests.test_0114_fk_ondelete import _scratch
from tests.test_alembic_chain import VERSIONS_DIR, _url_postgres_ci


def _head_revision() -> str:
    """Head real de la cadena, sin literal: un head nuevo (0118, ...) no
    debe romper este test, que vigila la reentrada de 0117, no el extremo."""
    from alembic.script import ScriptDirectory

    cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
    return ScriptDirectory.from_config(cfg).get_current_head()

_NOMBRES = [
    "ix_catalysts_source_id",
    "ix_connector_states_company_id",
    "ix_dca_signal_states_company_id",
    "ix_external_claims_company_id",
    "ix_external_claims_source_id",
    "ix_financial_facts_source_id",
    "ix_financial_statements_source_id",
    "ix_source_audits_thesis_version_id",
    "ix_transcripts_source_id",
]

_ESTADO = (
    "select c.relname, i.indisvalid, i.indisready from pg_class c "
    "join pg_index i on i.indexrelid = c.oid "
    "join pg_class t on t.oid = i.indrelid "
    "where c.relname = any(:nombres) and t.relnamespace = 'public'::regnamespace"
)

_OIDS = (
    "select c.relname, c.oid from pg_class c "
    "join pg_index i on i.indexrelid = c.oid "
    "join pg_class t on t.oid = i.indrelid "
    "where c.relname = any(:nombres) and t.relnamespace = 'public'::regnamespace"
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
        get_settings.cache_clear()


def test_0117_repara_invalidos_propios_respeta_ajenos_y_es_reentrante_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo en el job Postgres con CAVAAI_ORIGINAL_DATABASE_URL")
    scratch, scratch_url, admin = _scratch(url)
    engine = sa.create_engine(scratch_url)
    try:
        _alembic(scratch_url, command.downgrade, "0116_insider_filings_ticker")
        with engine.begin() as conn:
            assert conn.execute(sa.text(_ESTADO), {"nombres": _NOMBRES}).all() == []
            # INVALID propio (intento interrumpido simulado via catalogo)
            conn.execute(sa.text(
                "create index ix_transcripts_source_id on transcripts (source_id)"
            ))
            conn.execute(sa.text(
                "update pg_index set indisvalid = false "
                "where indexrelid = 'ix_transcripts_source_id'::regclass"
            ))
            # INVALID homonimo en OTRO schema: NO debe tocarse
            conn.execute(sa.text("create schema otro"))
            conn.execute(sa.text("create table otro.t (x int)"))
            conn.execute(sa.text("create index ix_transcripts_source_id on otro.t (x)"))
            conn.execute(sa.text(
                "update pg_index set indisvalid = false "
                "where indexrelid = 'otro.ix_transcripts_source_id'::regclass"
            ))
            oid_ajeno = conn.execute(sa.text(
                "select 'otro.ix_transcripts_source_id'::regclass::oid"
            )).scalar_one()

        _alembic(scratch_url, command.upgrade, "head")

        with engine.connect() as conn:
            estado = {
                r[0]: (r[1], r[2])
                for r in conn.execute(sa.text(_ESTADO), {"nombres": _NOMBRES}).all()
            }
            ajeno = conn.execute(sa.text(
                "select i.indisvalid from pg_index i where i.indexrelid = :oid"
            ), {"oid": oid_ajeno}).scalar_one()
        assert set(estado) == set(_NOMBRES), estado
        assert all(v and r for v, r in estado.values()), estado
        assert ajeno is False, "el INVALID de otro schema se toco"

        # reentrada real: stamp a 0116 con los 9 validos y upgrade de nuevo
        with engine.connect() as conn:
            oids_antes = dict(
                conn.execute(sa.text(_OIDS), {"nombres": _NOMBRES}).all()
            )
        assert set(oids_antes) == set(_NOMBRES)
        _alembic(scratch_url, command.stamp, "0116_insider_filings_ticker")
        _alembic(scratch_url, command.upgrade, "head")
        with engine.connect() as conn:
            oids_despues = dict(
                conn.execute(sa.text(_OIDS), {"nombres": _NOMBRES}).all()
            )
            estado2 = {
                r[0]: (r[1], r[2])
                for r in conn.execute(sa.text(_ESTADO), {"nombres": _NOMBRES}).all()
            }
            version = conn.execute(
                sa.text("select version_num from alembic_version")
            ).scalar_one()
        assert oids_despues == oids_antes, "recreo indices ya validos"
        assert all(v and r for v, r in estado2.values())
        assert version == _head_revision()
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- fixture: nombre scratch uuid-hex del fixture _scratch (test_0114), sin input externo; BD efimera de CI
        admin.dispose()
