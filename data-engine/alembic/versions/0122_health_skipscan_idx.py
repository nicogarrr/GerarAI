"""Indices para el barrido perezoso (skip scan) de data-health y metric-coverage.
Revision ID: 0122_health_skipscan_idx
Revises: 0121_alerts_home_feed_idx
Create Date: 2026-11-01T00:30:00.000Z
Criterio: solo se anade lo que MIDE mejor. El coste en frio de
/api/data-health y /api/screeners/metric-coverage seguia en 17-18 s en prod
(MEDIDO por el piloto tras la cache de 003c1644: antes
[19810,23,21009,19,17771] ms, ahora [17946,20,21,21,18] ms: solo mejora en
caliente). Causa medida en el laboratorio (PG 14, volumenes sinteticos con
forma de prod: 4,9M market_prices, 3,1M financial_facts, 1M documents,
1M news_events; SUPUESTO: distribucion): el group-by con count(distinct
company_id) lee TODA la porcion de la capa (926 ms facts, 610 ms precios,
182 ms docs, 175 ms news, en caliente) y el distinct de facts 150 ms.
El servicio pasa a un barrido perezoso por CTE recursiva (una sonda por par
fuente-empresa distinto: miles, no millones) y a sondas puntuales de
max(updated_at) por fuente. Estos indices hacen cada sonda O(log n):
- (tenant_id, source[_type], company_id) parcial: salta por pares dentro
  del tenant con los mismos filtros del panel.
- (tenant_id, source[_type], updated_at) parcial: max por fuente en una
  sonda hacia atras.
- market_prices ya tenia (source, company_id, updated_at) de 0119 para el
  salto; solo le falta (source, updated_at) para el max.
- (tenant_id, metric) en financial_facts: salto por metrica del distinct.
Medido en el laboratorio, mismos datos, resultado identico: 1.088 ms ->
107 ms las cuatro capas de data-health; distinct facts 150 ms -> 4 ms.
Mismo patron que 0117/0119: CONCURRENTLY en autocommit_block, IF NOT
EXISTS, INVALID propio por tabla recreado; sqlite con guard por inspector.
Modelos alineados (Index con postgresql_where, mismos nombres).
Pendiente de aplicar en produccion (sin despliegue en este commit).
"""
import sqlalchemy as sa

from alembic import op

revision = "0122_health_skipscan_idx"
down_revision = "0121_alerts_home_feed_idx"
branch_labels = None
depends_on = None

_NO_REALES = "('seed', 'manual', 'test', 'dummy', 'placeholder')"
_INDICES = [
    (
        "ix_facts_health_src_cid",
        "financial_facts",
        ["tenant_id", "source_type", "company_id"],
        f"is_reported AND source_type NOT IN {_NO_REALES} AND company_id IS NOT NULL",
    ),
    (
        "ix_facts_health_src_upd",
        "financial_facts",
        ["tenant_id", "source_type", "updated_at"],
        f"is_reported AND source_type NOT IN {_NO_REALES} AND company_id IS NOT NULL",
    ),
    (
        "ix_facts_tenant_metric",
        "financial_facts",
        ["tenant_id", "metric"],
        None,
    ),
    (
        "ix_docs_health_src_cid",
        "documents",
        ["tenant_id", "source_type", "company_id"],
        f"source_type NOT IN {_NO_REALES} AND company_id IS NOT NULL",
    ),
    (
        "ix_docs_health_src_upd",
        "documents",
        ["tenant_id", "source_type", "updated_at"],
        f"source_type NOT IN {_NO_REALES} AND company_id IS NOT NULL",
    ),
    (
        "ix_news_health_src_cid",
        "news_events",
        ["tenant_id", "source", "company_id"],
        f"source NOT IN {_NO_REALES} AND company_id IS NOT NULL",
    ),
    (
        "ix_news_health_src_upd",
        "news_events",
        ["tenant_id", "source", "updated_at"],
        f"source NOT IN {_NO_REALES} AND company_id IS NOT NULL",
    ),
    (
        "ix_prices_source_upd",
        "market_prices",
        ["source", "updated_at"],
        "close > 0",
    ),
]


def _es_invalido(bind, nombre: str, tabla: str) -> bool:
    """True si EXISTE un indice INVALID llamado ``nombre`` sobre ESA tabla.

    Un intento CONCURRENTLY interrumpido deja el indice con indisvalid =
    false. Se comprueba por tabla (indrelid via search_path) y no solo por
    nombre: un indice homonimo de otro schema o de otra tabla no se toca.
    """
    return bool(
        bind.execute(
            sa.text(
                "select 1 from pg_index i "
                "join pg_class idx on idx.oid = i.indexrelid "
                "where i.indrelid = cast(:tabla as regclass) "
                "and idx.relname = :nombre and not i.indisvalid"
            ),
            {"tabla": tabla, "nombre": nombre},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, columnas, where in _INDICES:
                if _es_invalido(bind, nombre, tabla):
                    op.drop_index(
                        nombre,
                        table_name=tabla,
                        postgresql_concurrently=True,
                        if_exists=True,
                    )
                op.create_index(
                    nombre,
                    tabla,
                    columnas,
                    postgresql_concurrently=True,
                    if_not_exists=True,
                    postgresql_where=sa.text(where) if where else None,
                )
        return
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, columnas, where in _INDICES:
        if nombre not in existentes:
            op.create_index(
                nombre, tabla, columnas, sqlite_where=sa.text(where) if where else None
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for nombre, tabla, _, _ in _INDICES:
                op.drop_index(
                    nombre,
                    table_name=tabla,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        return
    inspector = sa.inspect(bind)
    existentes = {
        ix["name"]
        for tabla in {t for _, t, _, _ in _INDICES}
        for ix in inspector.get_indexes(tabla)
    }
    for nombre, tabla, _, _ in _INDICES:
        if nombre in existentes:
            op.drop_index(nombre, table_name=tabla)
