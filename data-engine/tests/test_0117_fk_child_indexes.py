"""0117: CREATE INDEX CONCURRENTLY, idempotente y repara indices INVALID.

Gated al job Postgres. Un intento CONCURRENTLY interrumpido deja el indice
con indisvalid = false; IF NOT EXISTS lo saltaria y quedaria inservible.
0117 detecta ese estado, lo borra con DROP INDEX CONCURRENTLY y lo recrea.
El indice invalido se simula tocando el catalogo (update pg_index), que es
la unica forma determinista de reproducirlo en test.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from tests.test_0114_fk_ondelete import _scratch
from tests.test_alembic_chain import _url_postgres_ci

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
    "join pg_index i on i.indexrelid = c.oid where c.relname = any(:nombres)"
)


def _upgrade(cfg_url: str, revision: str) -> None:
    import os

    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings
    from tests.test_alembic_chain import VERSIONS_DIR

    anterior = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = cfg_url
    get_settings.cache_clear()
    try:
        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        command.upgrade(cfg, revision)
    finally:
        if anterior:
            os.environ["DATABASE_URL"] = anterior
        get_settings.cache_clear()


def test_0117_concurrently_repara_invalidos_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo en el job Postgres con CAVAAI_ORIGINAL_DATABASE_URL")
    scratch, scratch_url, admin = _scratch(url)
    engine = sa.create_engine(scratch_url)
    try:
        # ya migrada a head por _scratch: downgrade a 0116 para rejugar 0117
        import os

        from alembic.config import Config

        from alembic import command
        from app.core.config import get_settings
        from tests.test_alembic_chain import VERSIONS_DIR

        anterior = os.environ.get("DATABASE_URL", "")
        os.environ["DATABASE_URL"] = scratch_url
        get_settings.cache_clear()
        try:
            cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
            cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
            command.downgrade(cfg, "0116_insider_filings_ticker")
        finally:
            if anterior:
                os.environ["DATABASE_URL"] = anterior
            get_settings.cache_clear()

        with engine.begin() as conn:
            assert conn.execute(
                sa.text(_ESTADO), {"nombres": _NOMBRES}
            ).all() == []
            # indice preexistente INVALID (intento interrumpido simulado)
            conn.execute(sa.text(
                "create index ix_transcripts_source_id on transcripts (source_id)"
            ))
            conn.execute(sa.text(
                "update pg_index set indisvalid = false "
                "where indexrelid = 'ix_transcripts_source_id'::regclass"
            ))

        _upgrade(scratch_url, "head")

        with engine.connect() as conn:
            estado = dict(
                (r[0], (r[1], r[2]))
                for r in conn.execute(sa.text(_ESTADO), {"nombres": _NOMBRES}).all()
            )
        assert set(estado) == set(_NOMBRES), estado
        assert all(v and r for v, r in estado.values()), estado  # validos y listos

        # idempotente: relanzar 0117 no rompe nada y mantiene los 9 validos
        _upgrade(scratch_url, "head")
        with engine.connect() as conn:
            estado2 = dict(
                (r[0], (r[1], r[2]))
                for r in conn.execute(sa.text(_ESTADO), {"nombres": _NOMBRES}).all()
            )
        assert all(v and r for v, r in estado2.values())
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()
