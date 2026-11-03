"""Indice parcial de candidatos a margen para metric-coverage.
Revision ID: 0124_val_outputs_margin_idx
Revises: 0123_workflow_tracked_ticker_idx
Create Date: 2026-11-03T10:30:00.000Z

Criterio: solo se anade lo que MIDE mejor. _any_margin_of_safety proyectaba
margen/convenio/tipo de TODOS los outputs de los ultimos modelos (el piloto
midio esa extraccion en 3.420 ms en prod); la sonda 0124 filtra candidatos
por convenio conocido + valor ni booleano ni nulo. Medido en el laboratorio
(PG 16, 213.700 valuation_outputs con forma de prod: ultimo modelo por
empresa con margen numerico en todas salvo 6 outputs de convenio viejo;
SUPUESTO: volumen y reparto):
- Ruta anterior (proyeccion ORM de todos los outputs): 1.230-1.400 ms.
- Sonda con este indice parcial: 2-3 ms (-99,8%), mismo resultado
  (bateria de bordes: null/true/"NaN"/"Infinity"/"no numerico"/{}/[]
  rechazados igual; "0.25" aceptado igual).

El literal del convenio va en linea en el predicado (un parametro bound no
matchea predicados de indice parcial) y replica MARGIN_OF_SAFETY_CONVENTION
(app/valuation/margin_convention.py); un test fija que coinciden.

Mismo patron que 0119/0122/0123: CONCURRENTLY en autocommit_block, IF NOT
EXISTS, INVALID propio por tabla recreado; sqlite con guard por
sqlite_master (indice plano: json_typeof no existe en sqlite y el modelo
solo declara postgresql_where). Modelo alineado (mismo Index y nombre).
"""
import sqlalchemy as sa

from alembic import op

revision = "0124_val_outputs_margin_idx"
down_revision = "0123_workflow_tracked_ticker_idx"
branch_labels = None
depends_on = None

_NOMBRE = "ix_val_outputs_margin_candidate"
_TABLA = "valuation_outputs"
_COLUMNAS = ["tenant_id", "valuation_model_id"]
_WHERE_PG = (
    "(output_payload -> 'trace' ->> 'margin_of_safety_convention')"
    " = 'discount_to_value_v1'"
    " AND json_typeof(output_payload -> 'margin_of_safety')"
    " NOT IN ('boolean', 'null')"
)


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
                postgresql_where=sa.text(_WHERE_PG),
            )
        return
    # sqlite: el inspector no refleja indices con predicado de expresion;
    # se crea plano (sin where) y la existencia se mira en sqlite_master.
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
