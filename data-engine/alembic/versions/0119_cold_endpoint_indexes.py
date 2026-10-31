"""Indices para endpoints en frio: data-health y metric-coverage.

Revision ID: 0119_cold_endpoint_indexes
Revises: 0118_thesis_attention_idx
Create Date: 2026-10-31T14:40:00.000Z

Orden de Nico (2026-10-31): solo se aplica lo que MIDA mejor. Laboratorio
EXPLAIN (ANALYZE, BUFFERS) en PG 16.2 sobre BD scratch migrada a head con
volumenes sinteticos con forma de prod (5 tenants, ~2.132 empresas LEIDO del
docstring de data_health, ~256k market_prices, ~256k financial_facts,
~106k calculated_metrics; SUPUESTO: distribucion):

- data-health, capa Precios diarios (group by source, count distinct
  company_id, max(updated_at), close > 0): Seq Scan + agregacion con spill a
  temp (181 ms) -> Index Only Scan sin spill (102 ms). market_prices es
  global (sin tenant_id): era la unica consulta del panel sin indice usable.
- metric-coverage, calculated_metrics (distinct metric con status='ok' y
  value not null): el planner elige el indice parcial (menos buffers,
  1443 -> 1422 hits ya en caliente; en frio el indice parcial evita el heap
  para las filas que no cumplen).
- RESTO auditado y DESCARTADO por no medir mejora: financial_facts,
  documents y news_events ya resuelven con los indices ix_*_tenant_id de
  0117 (Bitmap Heap Scan selectivo por tenant); attention-thesis quedo
  cubierto por 0118 (0,5-0,6 ms en el laboratorio).

Mismo patron que 0117: CREATE INDEX CONCURRENTLY dentro de
op.get_context().autocommit_block() (los Dockerfiles migran al arrancar y
un CREATE INDEX normal bloquearia escrituras), IF NOT EXISTS como guard,
INVALID propio detectado por tabla (indrelid via search_path) y recreado;
sqlite con guard por inspector. Predicados parciales identicos a los
filtros de las consultas para que el planner pueda usarlos.

Modelos alineados (Index con postgresql_where, mismos nombres): el rachet
no crece.

NO desplegar en produccion hasta que Nico lo decida.
"""

import sqlalchemy as sa

from alembic import op

revision = "0119_cold_endpoint_indexes"
down_revision = "0118_thesis_attention_idx"
branch_labels = None
depends_on = None

_INDICES = [
    (
        "ix_market_prices_source_cov",
        "market_prices",
        ["source", "company_id", "updated_at"],
        "close > 0",
    ),
    (
        "ix_calc_metrics_tenant_metric_ok",
        "calculated_metrics",
        ["tenant_id", "metric"],
        "status = 'ok' AND value IS NOT NULL",
    ),
]


def _es_invalido(bind, nombre: str, tabla: str) -> bool:
    """True si EXISTE un indice INVALID llamado ``nombre`` sobre ESA tabla.

    Un intento CONCURRENTLY interrumpido deja el indice con indisvalid =
    false. Se comprueba por tabla (indrelid resuelto via search_path, o sea
    el schema efectivo) y no solo por nombre: un indice homonimo de otro
    schema o de otra tabla no se toca.
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
                    postgresql_where=sa.text(where),
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
            op.create_index(nombre, tabla, columnas, sqlite_where=sa.text(where))


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
