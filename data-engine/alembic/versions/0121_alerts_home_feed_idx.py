"""Indice de lectura para el feed de alertas del inicio (/api/alerts).

Revision ID: 0121_alerts_home_feed_idx
Revises: 0120_news_screener_read_indexes
Create Date: 2026-10-31T16:05:00.000Z

Motivo: la server action getHomeOverviewBundle de /inicio tarda ~1,4 s en
servidor (perfil de UX movil en prod) y una de sus patas es
GET /api/alerts?limit=3 (ultimos disparos), cuyo propio diagnostico
ALERTS_TIMING registra prod p50 263 ms.

MEDIDO (EXPLAIN (ANALYZE, BUFFERS), PG 16.2 local migrada a head, 50.000
research_alerts sinteticas con forma de prod, 80% tenant 1; prod corre
PG 17, la forma del plan es la que cuenta):

- Consulta del listado con scope de tenant (la que sirve prod
  autenticado): Seq Scan + top-N heapsort por
  coalesce(last_triggered_at, created_at) DESC para devolver 3 filas,
  24,1 ms y 902 buffers -> Index Scan con parada temprana, 0,047 ms y
  6 buffers (~500x).
- El filtro de audiencia (metadata->>'audience') y el de snooze con
  now() no son indexables de forma estable (now() no es IMMUTABLE); se
  quedan como Filter sobre las pocas filas que recorre el walk, que es
  el patron correcto para un feed reciente.

Sin indice para el caso anonimo (sin tenant): prod /inicio es autenticado
y la consulta sin scope seguiria en Seq Scan; no se crea un segundo indice
que nadie mide mejor.

Mismo patron que 0117/0119: CONCURRENTLY + autocommit en PG, IF NOT
EXISTS, INVALID propio por tabla reparado; sqlite con guard contra sqlite_master (la reflexion salta indices
con expresiones; coalesce y DESC son validos en sqlite). Modelo alineado (mismo nombre).
"""

import sqlalchemy as sa

from alembic import op

revision = "0121_alerts_home_feed_idx"
down_revision = "0120_news_screener_read_indexes"
branch_labels = None
depends_on = None

_NOMBRE = "ix_research_alerts_home_feed"
_TABLA = "research_alerts"
_COLUMNAS = [
    "tenant_id",
    sa.text("coalesce(last_triggered_at, created_at) DESC"),
    sa.text("id DESC"),
]


def _es_invalido(bind) -> bool:
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
    # La reflexion de sqlite SALTA indices con expresiones (SAWarning), asi
    # que el guard se hace contra sqlite_master, no contra el inspector.
    existe = bind.execute(
        sa.text("select 1 from sqlite_master where type = 'index' and name = :n"),
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
        sa.text("select 1 from sqlite_master where type = 'index' and name = :n"),
        {"n": _NOMBRE},
    ).first()
    if existe:
        op.drop_index(_NOMBRE, table_name=_TABLA)
