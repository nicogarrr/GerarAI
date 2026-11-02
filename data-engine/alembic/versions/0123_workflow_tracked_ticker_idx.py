"""Indice de expresion para tracked_statuses (watchlist y cartera).
Revision ID: 0123_workflow_tracked_ticker_idx
Revises: 0122_health_skipscan_idx
Create Date: 2026-11-03T00:30:00.000Z

Criterio: solo se anade lo que MIDE mejor. tracked_statuses filtra por
tenant + workflow + ticker dentro del payload JSONB y antes hidrataba TODAS
las corridas historicas de esos tickers para quedarse con la ultima en
Python. Medido en el laboratorio (PG 16, 178.220 workflow_runs con forma de
prod: 60 corridas por ticker de 2.137 tickers del workflow de analisis,
ruido de otros workflows y de otro tenant; SUPUESTO: volumen y reparto):
- Sin indice: 40,4 ms por consulta (bitmap/seq sobre la porcion del tenant
  extrayendo input_payload->>'ticker' por fila).
- Con este indice: 5,4 ms (Index Scan de las 720 filas exactas).
- Con indice + ventana row_number (una fila por ticker, mismo resultado):
  1,9 ms (-95% frente al statu quo). Salida bit identica (el servicio solo
  usa la corrida mas reciente por ticker, orden id DESC).

Mismo patron que 0119/0122: CONCURRENTLY en autocommit_block, IF NOT
EXISTS, INVALID propio por tabla recreado; sqlite con guard por inspector
(sqlite >= 3.38 soporta ->>). Modelo alineado (Index con la misma
expresion y nombre).
"""
import sqlalchemy as sa

from alembic import op

revision = "0123_workflow_tracked_ticker_idx"
down_revision = "0122_health_skipscan_idx"
branch_labels = None
depends_on = None

_NOMBRE = "ix_workflow_runs_tracked_ticker"
_TABLA = "workflow_runs"
_COLUMNAS = ["tenant_id", "workflow_name", sa.text("(input_payload ->> 'ticker')")]


def _es_invalido(bind) -> bool:
    """True si EXISTE un indice INVALID con ese nombre sobre ESA tabla."""
    return bool(
        bind.execute(
            sa.text(
                "select 1 from pg_index i "
                "join pg_class idx on idx.oid = i.indexrelid "
                "where i.indrelid = cast(:tabla as regclass) "
                "and idx.relname = :nombre and not i.indisvalid"
            ),
            {"tabla": _TABLA, "nombre": _NOMBRE},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            if _es_invalido(bind):
                op.drop_index(
                    _NOMBRE,
                    table_name=_TABLA,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
            op.create_index(
                _NOMBRE,
                _TABLA,
                _COLUMNAS,
                postgresql_concurrently=True,
                if_not_exists=True,
            )
        return
    # sqlite no refleja indices de expresion por el inspector (SAWarning);
    # la existencia se comprueba en sqlite_master.
    existe = bind.execute(
        sa.text("select 1 from sqlite_master where type='index' and name=:n"),
        {"n": _NOMBRE},
    ).first()
    if not existe:
        op.create_index(_NOMBRE, _TABLA, _COLUMNAS)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(
                _NOMBRE,
                table_name=_TABLA,
                postgresql_concurrently=True,
                if_exists=True,
            )
        return
    existe = bind.execute(
        sa.text("select 1 from sqlite_master where type='index' and name=:n"),
        {"n": _NOMBRE},
    ).first()
    if existe:
        op.drop_index(_NOMBRE, table_name=_TABLA)
