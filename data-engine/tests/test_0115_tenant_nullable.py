"""0115: tenant_id queda nullable donde los modelos lo declaran.

Corre en el job 'Postgres migration round trip' sobre una BD scratch
desechable que crea y destruye el propio test. En local/sqlite hace skip
(la paridad sqlite la cubre la cadena completa en test_alembic_chain).
"""

import pytest

from tests.test_0114_fk_ondelete import _fks  # noqa: F401  (patron scratch compartido)
from tests.test_alembic_chain import _url_postgres_ci

_TABLAS = [
    "alert_subscriptions",
    "decision_journal_entries",
    "expectation_reviews",
    "fundamental_assumptions",
    "fundamental_drivers",
    "fundamental_forecasts",
    "fundamental_model_versions",
    "telegram_chat_bindings",
    "telegram_link_challenges",
]

_NULLABLE_SQL = (
    "select table_name, is_nullable from information_schema.columns "
    "where column_name = 'tenant_id' and table_name = any(:tablas)"
)


def _nullables(url: str) -> dict:
    import sqlalchemy as sa

    engine = sa.create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(sa.text(_NULLABLE_SQL), {"tablas": _TABLAS}).all()
    engine.dispose()
    return {r[0]: r[1] for r in rows}


def _migra(cfg_args):
    import os

    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings
    from tests.test_alembic_chain import VERSIONS_DIR

    url, revision = cfg_args
    anterior = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        if revision == "head":
            command.upgrade(cfg, "head")
        else:
            command.downgrade(cfg, revision)
    finally:
        if anterior:
            os.environ["DATABASE_URL"] = anterior
        get_settings.cache_clear()


def test_0115_tenant_nullable_en_ci_postgres():
    url = _url_postgres_ci()
    if not url:
        pytest.skip("Runs only on the CI Postgres migration service")
    import re
    import uuid

    import sqlalchemy as sa

    scratch = "nn115_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))
    base, sep, query = url.partition("?")
    base = re.sub(r"/[^/]+$", f"/{scratch}", base)
    scratch_url = base + (sep + query if sep else "")
    try:
        _migra((scratch_url, "head"))
        estado = _nullables(scratch_url)
        assert set(estado) == set(_TABLAS)
        assert all(v == "YES" for v in estado.values()), estado

        _migra((scratch_url, "0114_fk_ondelete_tenants"))
        estado = _nullables(scratch_url)
        assert all(v == "NO" for v in estado.values()), estado

        _migra((scratch_url, "head"))
        estado = _nullables(scratch_url)
        assert all(v == "YES" for v in estado.values()), estado
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()
