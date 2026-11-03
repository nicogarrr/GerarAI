"""Indices parciales de carril para el feed de noticias (macro/gobierno).
Revision ID: 0125_news_lane_idx
Revises: 0124_val_outputs_margin_idx
Create Date: 2026-11-03T11:00:00.000Z

Criterio: solo se anade lo que MIDE mejor. Los carriles macro/gobierno de
/api/news filtran por metadata->>'news_lane' sobre la tabla completa: con
carriles escasos el barrido por chunks visita hasta 2.000 filas por pagina
con extraccion JSON por fila. Medido en el laboratorio (PG16, 1M noticias;
gobierno 500 filas / macro 2.000; SUPUESTO: densidad; prod tiene las mismas
fuentes oficiales escasas):
- gobierno: 95-96 ms -> esperado ~5 ms con el indice parcial (ABBA abajo en
  la PR, verificado con EXPLAIN: el literal en linea es lo que permite
  matchear el predicado; un parametro bound jamas lo matchea).

Mismo patron que 0122/0123/0124: CONCURRENTLY en autocommit_block, IF NOT
EXISTS, INVALID propio por tabla recreado; sqlite con sqlite_where (sqlite
>= 3.38 soporta ->> en predicados de indice). Modelo alineado (mismos Index
y nombres).
"""
import sqlalchemy as sa

from alembic import op

revision = "0125_news_lane_idx"
down_revision = "0124_val_outputs_margin_idx"
branch_labels = None
depends_on = None

_TABLA = "news_events"
_INDICES = (
    ("ix_news_lane_gobierno", "(metadata ->> 'news_lane') = 'gobierno'"),
)
# Macro NO lleva indice propio: ix_news_events_macro_date_id (0120) ya es
# (date DESC, id DESC) WHERE metadata->>'news_lane' = 'macro', identico. Un
# duplicado solo anadia escritura a cada insert de news_events. Las bases que
# corrieron la primera version de esta 0125 lo pierden aqui (IF EXISTS).
_DUPLICADO_RETIRADO = "ix_news_lane_macro"
_COLUMNAS = [sa.desc("date"), sa.desc("id")]


def _es_invalido(bind, nombre: str) -> bool:
    """True si EXISTE un indice INVALID con ese nombre sobre ESA tabla."""
    return bool(
        bind.execute(
            sa.text(
                "select 1 from pg_index i "
                "join pg_class idx on idx.oid = i.indexrelid "
                "where i.indrelid = cast(:tabla as regclass) "
                "and idx.relname = :nombre and not i.indisvalid"
            ),
            {"tabla": _TABLA, "nombre": nombre},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(
                _DUPLICADO_RETIRADO,
                table_name=_TABLA,
                postgresql_concurrently=True,
                if_exists=True,
            )
            for nombre, where in _INDICES:
                if _es_invalido(bind, nombre):
                    op.drop_index(
                        nombre,
                        table_name=_TABLA,
                        postgresql_concurrently=True,
                        if_exists=True,
                    )
                op.create_index(
                    nombre,
                    _TABLA,
                    _COLUMNAS,
                    postgresql_concurrently=True,
                    if_not_exists=True,
                    postgresql_where=sa.text(where),
                )
        return
    # sqlite soporta ->> en predicados de indice (>= 3.38); existencia por
    # sqlite_master porque el inspector no refleja indices de expresion.
    existentes = {
        row[0]
        for row in bind.execute(
            sa.text("select name from sqlite_master where type='index'")
        )
    }
    if _DUPLICADO_RETIRADO in existentes:
        op.drop_index(_DUPLICADO_RETIRADO, table_name=_TABLA)
    for nombre, where in _INDICES:
        if nombre not in existentes:
            op.create_index(nombre, _TABLA, _COLUMNAS, sqlite_where=sa.text(where))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, _ in _INDICES:
                op.drop_index(
                    nombre,
                    table_name=_TABLA,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        return
    for nombre, _ in _INDICES:
        op.drop_index(nombre, table_name=_TABLA, if_exists=True)
