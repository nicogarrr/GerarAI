"""0131: indices del dedup de ingesta presentes, validos, parciales y reentrantes.

Corre en el job 'Postgres migration round trip' sobre una BD scratch
desechable migrada a head. En sqlite/local hace skip. Replica el patron del
gate de 0122 (misma clase de migracion: CREATE INDEX CONCURRENTLY con
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

_NOMBRES = [
    "ix_documents_tenant_source_url",
    "ix_documents_company_checksum",
]

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


def test_0131_indices_validos_parciales_y_reentrantes_en_ci_postgres():
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
        # predicados parciales tal y como los filtran los dedups
        assert "source_url IS NOT NULL" in estado["ix_documents_tenant_source_url"][2]
        assert "checksum IS NOT NULL" in estado["ix_documents_company_checksum"][2]

        # reentrada real: stamp a 0130 con los 2 validos y upgrade de nuevo
        with engine.connect() as conn:
            oids_antes = dict(conn.execute(sa.text(_OIDS), {"nombres": _NOMBRES}).all())
        assert set(oids_antes) == set(_NOMBRES)
        _alembic(scratch_url, command.stamp, "0130_analyst_notes")
        _alembic(scratch_url, command.upgrade, "head")
        with engine.connect() as conn:
            oids_despues = dict(conn.execute(sa.text(_OIDS), {"nombres": _NOMBRES}).all())
        assert oids_despues == oids_antes, "recreo indices ya validos"
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- fixture: nombre uuid-hex generado por _scratch (test_0114), sin input externo; BD efimera de CI
