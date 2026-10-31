"""0114: los FKs de la BD migrada coinciden con los modelos (ondelete y tenant).

Corre en el job 'Postgres migration round trip' sobre una BD scratch
desechable que crea y destruye el propio test. En sqlite/local hace skip:
sqlite no puede recrear FKs sin nombre y los tests hermeticos no enforzan
ondelete.
"""

import pytest

from tests.test_alembic_chain import _url_postgres_ci

_TABLAS_TENANT = [
    "decision_journal_entries",
    "expectation_reviews",
    "fundamental_assumptions",
    "fundamental_drivers",
    "fundamental_forecasts",
    "fundamental_model_versions",
]

_DELTYPE = {"c": "CASCADE", "n": "SET NULL", "a": None, "r": "RESTRICT", "d": "SET DEFAULT"}

_FKS_SQL = (
    "select c.conrelid::regclass::text, a.attname, c.conname, c.confdeltype, c.convalidated "
    "from pg_constraint c join pg_attribute a "
    "on a.attrelid = c.conrelid and a.attnum = c.conkey[1] "
    "where c.contype = 'f' and array_length(c.conkey, 1) = 1"
)


def _scratch(url: str):
    """Crea una BD scratch, la migra a head y devuelve (nombre, url, engine)."""
    import re
    import uuid

    import sqlalchemy as sa
    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings

    scratch = "fk114_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
    base, sep, query = url.partition("?")
    base = re.sub(r"/[^/]+$", f"/{scratch}", base)
    scratch_url = base + (sep + query if sep else "")
    import os

    anterior = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = scratch_url
    get_settings.cache_clear()
    try:
        from tests.test_alembic_chain import VERSIONS_DIR

        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        command.upgrade(cfg, "head")
    finally:
        if anterior:
            os.environ["DATABASE_URL"] = anterior
        get_settings.cache_clear()
    return scratch, scratch_url, admin


def _fks(engine_url: str) -> dict:
    import sqlalchemy as sa

    engine = sa.create_engine(engine_url)
    with engine.connect() as conn:
        rows = conn.execute(sa.text(_FKS_SQL)).all()
    engine.dispose()
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


def test_0114_fks_coinciden_con_modelos_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    import sqlalchemy as sa

    import app.models  # noqa: F401  (registra las tablas en Base.metadata)
    from app.core.database import Base

    scratch, scratch_url, admin = _scratch(url)
    try:
        fks = _fks(scratch_url)
        # Cada FK declarado en los modelos existe y con el ondelete declarado.
        ausentes = []
        distintos = []
        for tabla in Base.metadata.sorted_tables:
            for fk in tabla.foreign_keys:
                clave = (tabla.name, fk.parent.name)
                if clave not in fks:
                    ausentes.append(clave)
                elif fks[clave][1] != "a" and _DELTYPE[fks[clave][1]] != fk.ondelete or fks[clave][1] == "a" and fk.ondelete:
                    distintos.append((clave, fk.ondelete, fks[clave][1]))
        assert not ausentes, f"FKs de modelos ausentes en la BD migrada: {ausentes}"
        assert not distintos, f"ondelete distinto modelo vs BD: {distintos[:10]}"
        # Los 6 FKs de tenant llegaron con nombre explicito.
        for tabla in _TABLAS_TENANT:
            assert (tabla, "tenant_id") in fks
            assert fks[(tabla, "tenant_id")][0] == f"fk_{tabla}_tenant_id"
        # Patron prod-seguro: los 59 nuevos/reescritos quedan NOT VALID;
        # VALIDATE es paso operativo aparte, a decidir por Nico.
        no_validados = sorted(k for k, v in fks.items() if v[2] is False)
        assert len(no_validados) == 59, no_validados[:5]

        # El downgrade revierte: FKs de tenant fuera y los 53 de vuelta a NO ACTION.
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
            command.downgrade(cfg, "0113_add_model_indexes")
        finally:
            if anterior:
                os.environ["DATABASE_URL"] = anterior
            get_settings.cache_clear()
        fks_down = _fks(scratch_url)
        for tabla in _TABLAS_TENANT:
            assert (tabla, "tenant_id") not in fks_down
        rever = [k for k, v in fks_down.items() if v[2] is False]
        assert len(rever) == 53  # los recreados NO ACTION quedan NOT VALID
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()


def test_0114_ondelete_rige_sin_validate_en_ci_postgres():
    """NOT VALID no aplaza la semantica: borrar un padre ya cascada/NULL-ea.

    Fija la afirmacion corregida del body: las acciones ON DELETE estan
    activas desde el DDL, con la constraint todavia NOT VALID.
    """
    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    import re
    import uuid

    import sqlalchemy as sa

    scratch = "fk114del_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
    base, sep, query = url.partition("?")
    base = re.sub(r"/[^/]+$", f"/{scratch}", base)
    scratch_url = base + (sep + query if sep else "")
    try:
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
            command.upgrade(cfg, "head")
        finally:
            if anterior:
                os.environ["DATABASE_URL"] = anterior
            get_settings.cache_clear()

        engine = sa.create_engine(scratch_url)
        with engine.begin() as conn:
            # CASCADE: documents -> document_chunks (constraint NOT VALID)
            not_valid_antes = conn.execute(sa.text(
                "select convalidated from pg_constraint where conrelid = 'document_chunks'::regclass "
                "and contype = 'f'")).scalar()
            assert not_valid_antes is False
            doc_id = conn.execute(sa.text(
                "insert into documents (title, source_type, metadata, created_at, updated_at) "
                "values ('d114', 'test', '{}', now(), now()) returning id")).scalar()
            conn.execute(sa.text(
                "insert into document_chunks (document_id, chunk_index, text, token_count, metadata, "
                "created_at, updated_at) values (:d, 0, 'c0', 1, '{}', now(), now()), "
                "(:d, 1, 'c1', 1, '{}', now(), now())"), {"d": doc_id})
            conn.execute(sa.text("delete from documents where id = :d"), {"d": doc_id})
            restantes = conn.execute(sa.text(
                "select count(*) from document_chunks where document_id = :d"), {"d": doc_id}).scalar()
            assert restantes == 0, "CASCADE no actuo con la constraint NOT VALID"

            # SET NULL: research_sessions -> memory_items.research_session_id
            rs_id = conn.execute(sa.text(
                "insert into research_sessions (title, question, summary, status, claim_ids, "
                "memory_item_ids, source_ids, metadata, created_at, updated_at) values ('s114', "
                "'q', 'r', 'done', '[]', '[]', '[]', '{}', now(), now()) returning id")).scalar()
            mem_id = conn.execute(sa.text(
                "insert into memory_items (content, memory_type, scope, source_type, status, "
                "importance, metadata, research_session_id, created_at, updated_at) values ('m114', "
                "'fact', 'session', 'test', 'active', 1, '{}', :rs, now(), now()) returning id"),
                {"rs": rs_id}).scalar()
            conn.execute(sa.text("delete from research_sessions where id = :rs"), {"rs": rs_id})
            valor = conn.execute(sa.text(
                "select research_session_id from memory_items where id = :m"), {"m": mem_id}).scalar()
            assert valor is None, "SET NULL no actuo con la constraint NOT VALID"
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()
