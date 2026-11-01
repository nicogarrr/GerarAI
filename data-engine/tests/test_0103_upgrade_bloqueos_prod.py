"""Upgrade 0103 -> head con los dos bloqueos medidos en prod (2026-10-31).

Prod esta en 0103_transaction_fees_4dp y el piloto midio (sin mutar prod):

- news_events.title: 7 filas por encima de 400 caracteres, maximo 467. La
  0105 original (title 500 -> 400) abortaria el upgrade; ahora 0105 conserva
  VARCHAR(500) y este test exige que un titulo de 467 caracteres sobreviva.
- transactions: 74 filas con price < 0 legitimas (fee 8, interest 30,
  withholding 36; IBKR Flex entrega esas salidas de caja con signo negativo y
  el XIRR depende de el). La 0108 original (price >= 0 para toda accion)
  fallaria al crear el CHECK; ahora nace con el predicado final
  ``price >= 0 OR action NOT IN ('buy', 'sell')``.

El test migra una BD scratch a 0103, siembra exactamente esas condiciones,
sube a head y comprueba: datos intactos, capacidad conservada, CHECKs en su
forma final (buy/sell negativo rechazado, caja negativa admitida, cortos de
positions admitidos desde 0111, market_prices.close >= 0 activo) y downgrade
head -> 0103 limpio con los datos intactos. En sqlite/local hace skip.
"""

import os
import re
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tests.test_0114_fk_ondelete import _validar_url_admin_ci
from tests.test_alembic_chain import VERSIONS_DIR, _url_postgres_ci

_REV_PROD = "0103_transaction_fees_4dp"

_NEGATIVAS_PROD = (("fee", 8), ("interest", 30), ("withholding", 36))  # censo piloto
_TITULO_467 = "N" * 467


def _upgrade(url_scratch: str, revision: str) -> None:
    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings

    anterior = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = url_scratch
    get_settings.cache_clear()
    try:
        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        command.upgrade(cfg, revision)
    finally:
        if anterior:
            os.environ["DATABASE_URL"] = anterior
        else:
            os.environ.pop("DATABASE_URL", None)
        get_settings.cache_clear()


def _downgrade(url_scratch: str, revision: str) -> None:
    from alembic.config import Config

    from alembic import command
    from app.core.config import get_settings

    anterior = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = url_scratch
    get_settings.cache_clear()
    try:
        cfg = Config(str(VERSIONS_DIR.parent.parent / "alembic.ini"))
        cfg.set_main_option("script_location", str(VERSIONS_DIR.parent))
        command.downgrade(cfg, revision)
    finally:
        if anterior:
            os.environ["DATABASE_URL"] = anterior
        else:
            os.environ.pop("DATABASE_URL", None)
        get_settings.cache_clear()


def _valor_por_defecto(col) -> object:
    """Valor minimo para una columna NOT NULL sin default en la BD."""
    tipo = col.data_type
    if tipo in ("integer", "bigint", "smallint"):
        return 1
    if tipo in ("numeric", "real", "double precision"):
        return 0
    if tipo in ("character varying", "character", "text"):
        return "x"
    if tipo == "boolean":
        return False
    if tipo == "date":
        return "2026-05-03"
    if tipo.startswith("timestamp"):
        return "2026-05-03T10:00:00+00:00"
    if tipo in ("json", "jsonb"):
        return "[]"
    if tipo == "ARRAY":
        return "{}"
    raise AssertionError(f"tipo NOT NULL sin default no cubierto: {col.column_name} {tipo}")


def _insert(conn, tabla: str, overrides: dict) -> int:
    """INSERT minimo: rellena NOT NULL sin default y aplica overrides. Devuelve id."""
    cols = conn.execute(
        sa.text(
            "select column_name, data_type from information_schema.columns "
            "where table_name = :t and is_nullable = 'NO' and column_default is null"
        ),
        {"t": tabla},
    ).all()
    existentes = {
        r[0]
        for r in conn.execute(
            sa.text(
                "select column_name from information_schema.columns where table_name = :t"
            ),
            {"t": tabla},
        )
    }
    valores = {c.column_name: _valor_por_defecto(c) for c in cols}
    # Solo overrides de columnas que existen en esta revision: el esquema a
    # 0103 aun no tiene tenant_id en todas las tablas tenant-scoped.
    valores.update({k: v for k, v in overrides.items() if k in existentes})
    campos = ", ".join(f'"{k}"' for k in valores)
    marcas = ", ".join(f":{k}" for k in valores)
    return conn.execute(
        sa.text(f'INSERT INTO "{tabla}" ({campos}) VALUES ({marcas}) RETURNING id'),  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- identificadores de information_schema escapados con comillas; valores ligados; sin input externo
        valores,
    ).scalar_one()


@pytest.fixture
def bd_en_0103_con_bloqueos():
    """BD scratch en 0103 con el censo exacto de bloqueos medido en prod."""
    url = _url_postgres_ci()
    if not url:
        pytest.skip("solo corre en el job de CI con Postgres")
    _validar_url_admin_ci(url)

    scratch = "p0103_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{scratch}"'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- fixture: nombre uuid-hex generado por el propio test, sin input externo; BD efimera de CI
        base, sep, query = url.partition("?")
        url_scratch = re.sub(r"/[^/]+$", f"/{scratch}", base) + (sep + query if sep else "")
        try:
            _upgrade(url_scratch, _REV_PROD)
            engine = sa.create_engine(url_scratch)
            with engine.begin() as conn:
                tenant = _insert(conn, "tenants", {"name": "Tenant prod-like"})
                company = _insert(conn, "companies", {"tenant_id": tenant, "ticker": "WHT"})
                portfolio = _insert(conn, "portfolios", {"tenant_id": tenant})
                _insert(
                    conn, "news_events",
                    {"tenant_id": tenant, "company_id": company, "title": _TITULO_467},
                )
                for accion, n in _NEGATIVAS_PROD:
                    for _ in range(n):
                        _insert(
                            conn, "transactions",
                            {
                                "tenant_id": tenant, "portfolio_id": portfolio,
                                "company_id": company, "trade_date": "2026-05-03",
                                "action": accion, "quantity": 1, "price": -15,
                                "fees": 0, "currency": "EUR",
                            },
                        )
                _insert(  # una compra normal, de control
                    conn, "transactions",
                    {
                        "tenant_id": tenant, "portfolio_id": portfolio,
                        "company_id": company, "trade_date": "2026-05-03",
                        "action": "buy", "quantity": 3, "price": 10,
                        "fees": 0, "currency": "EUR",
                    },
                )
            engine.dispose()
            yield scratch, url_scratch
        finally:
            with admin.connect() as conn:
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text -- fixture: nombre uuid-hex generado por el propio test, sin input externo; BD efimera de CI
    finally:
        admin.dispose()


def _uno(conn, sql: str, params: dict | None = None):
    return conn.execute(sa.text(sql), params or {}).fetchone()


def test_upgrade_0103_a_head_con_los_bloqueos_de_prod(bd_en_0103_con_bloqueos):
    _scratch, url_scratch = bd_en_0103_con_bloqueos

    _upgrade(url_scratch, "head")  # el punto del test: no aborta

    engine = sa.create_engine(url_scratch)
    with engine.connect() as conn:
        # (a) titulo intacto y capacidad conservada
        assert _uno(conn, "select length(title) from news_events")[0] == 467
        assert _uno(
            conn,
            "select character_maximum_length from information_schema.columns "
            "where table_name = 'news_events' and column_name = 'title'",
        )[0] == 500
        # (b) las 74 filas negativas y la compra siguen ahi, con su signo
        assert _uno(conn, "select count(*) from transactions where price < 0")[0] == 74
        assert _uno(conn, "select count(*) from transactions")[0] == 75

        # (c) forma final de los CHECKs en head
        with pytest.raises(IntegrityError):
            with engine.begin() as w:
                _insert(w, "transactions", {
                    "tenant_id": _uno(conn, "select id from tenants")[0],
                    "trade_date": "2026-05-03", "action": "buy",
                    "quantity": 1, "price": -1, "fees": 0, "currency": "EUR",
                })
        with pytest.raises(IntegrityError):
            with engine.begin() as w:
                _insert(w, "transactions", {
                    "tenant_id": _uno(conn, "select id from tenants")[0],
                    "trade_date": "2026-05-03", "action": "sell",
                    "quantity": 1, "price": -1, "fees": 0, "currency": "EUR",
                })
        with engine.begin() as w:  # caja negativa: admitida
            _insert(w, "transactions", {
                "tenant_id": _uno(conn, "select id from tenants")[0],
                "trade_date": "2026-05-03", "action": "cash_misc",
                "quantity": 1, "price": -7, "fees": 0, "currency": "EUR",
            })
        with engine.begin() as w:  # cortos: admitidos desde 0111
            _insert(w, "positions", {
                "tenant_id": _uno(conn, "select id from tenants")[0],
                "quantity": -5, "average_cost": 100, "market_price": 100,
                "market_value": -500, "currency": "EUR", "as_of": "2026-05-03",
            })
        with pytest.raises(IntegrityError):  # market_prices.close >= 0 sigue
            with engine.begin() as w:
                _insert(w, "market_prices", {
                    "company_id": _uno(conn, "select id from companies")[0],
                    "date": "2026-05-03", "close": -100,
                })

    # (d) downgrade head -> 0103 limpio y sin tocar los datos. Fuera del
    # with: la conexion de lectura abierta (idle in transaction) bloquearia
    # el DDL del downgrade.
    engine.dispose()
    _downgrade(url_scratch, _REV_PROD)
    engine2 = sa.create_engine(url_scratch)
    with engine2.connect() as conn2:
        assert _uno(conn2, "select length(title) from news_events")[0] == 467
        assert _uno(conn2, "select count(*) from transactions where price < 0")[0] == 75
    engine2.dispose()
