"""Indices cobertores para los DISTINCT de /api/screeners/metric-coverage.

Revision ID: 0119_metric_coverage_covering
Revises: 0118_thesis_attention_idx
Create Date: 2026-10-31T13:35:00.000Z

MEDIDO 2026-10-31 (benchmark local sqlite, 500 empresas, 240.000
financial_facts y 200.000 calculated_metrics): el camino frio de
metric-coverage son dos DISTINCT + contexto (~94 ms local; prod midio
15,8 s en frio antes de la cache de #3671). Los DISTINCT eran el tramo
dominante local (34,4 y 37,4 ms; el contexto, 11). Con los indices
cobertores bajan a 15,6 y 14,6 ms (EXPLAIN QUERY PLAN: SEARCH por el
indice sin tocar la tabla).

INFERIDO (no medido, lo dira el re-barrido post-deploy): en PG la mejora
es mayor que en sqlite. Hoy `SELECT DISTINCT metric ... WHERE tenant_id =
.. AND value IS NOT NULL AND status = 'ok'` exige un heap fetch por fila
de una tabla ANCHA (source_fact_ids y calculation_trace son JSON), solo
para leer `metric`. El indice (tenant_id, metric) parcial sobre las filas
que cumplen el predicado responde con un index-only scan de un indice
estrecho. En financial_facts no hay predicado: indice (tenant_id, metric)
plano.

Aditivo: dos CREATE INDEX, sin reescrituras ni cambios de datos. Guard por
inspector: idempotente. La migracion corre en una unica transaccion
(env.py), asi que no se usa CONCURRENTLY; es consistente con 0117/0118.

NO desplegar en produccion hasta que Nico lo decida.
"""

import sqlalchemy as sa

from alembic import op

revision = "0119_metric_coverage_covering"
down_revision = "0118_thesis_attention_idx"
branch_labels = None
depends_on = None

_IX_CALC = "ix_calculated_metrics_tenant_metric_ok"
_IX_FACTS = "ix_financial_facts_tenant_metric"
_PREDICADO = "value IS NOT NULL AND status = 'ok'"


def _existe_indice(bind, tabla: str, nombre: str) -> bool:
    return any(ix["name"] == nombre for ix in sa.inspect(bind).get_indexes(tabla))


def upgrade() -> None:
    bind = op.get_bind()
    if not _existe_indice(bind, "calculated_metrics", _IX_CALC):
        op.create_index(
            _IX_CALC,
            "calculated_metrics",
            ["tenant_id", "metric"],
            postgresql_where=sa.text(_PREDICADO),
            sqlite_where=sa.text(_PREDICADO),
        )
    if not _existe_indice(bind, "financial_facts", _IX_FACTS):
        op.create_index(
            _IX_FACTS,
            "financial_facts",
            ["tenant_id", "metric"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _existe_indice(bind, "financial_facts", _IX_FACTS):
        op.drop_index(_IX_FACTS, table_name="financial_facts")
    if _existe_indice(bind, "calculated_metrics", _IX_CALC):
        op.drop_index(_IX_CALC, table_name="calculated_metrics")
