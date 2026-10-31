"""Indice aditivo de thesis_changes para /api/attention-thesis.

Revision ID: 0118_thesis_attention_idx
Revises: 0117_fk_child_indexes
Create Date: 2026-10-31T12:24:00.000Z

MEDIDO (EXPLAIN ANALYZE BUFFERS capturado por el piloto, 2026-10-31, bajo
restore+build concurrentes; no comparable con la linea base tranquila de
414 ms p50): la consulta principal de /api/attention-thesis resolvio el
EXISTS de research_reviews como semijoin y sondo thesis_changes por
company_id: 466 sondas con ~64 filas reales cada una (estimaba rows=3) y
29.456 filas descartadas por el filtro de join id = thesis_change_id;
18.936 buffer hits en esa sola consulta.

Con (tenant_id, company_id, id) las tres condiciones disponibles en la
sonda (tenant constante, company_id del join con companies, id del join con
la subconsulta de research_reviews) van al indice: cada sonda toca 1 fila
en vez de ~64. La forma del plan no necesita cambiar.

Aditivo: un CREATE INDEX, sin reescrituras ni cambios de datos. Guard por
inspector: idempotente. La migracion corre en una unica transaccion
(env.py), asi que no se usa CONCURRENTLY; la tabla es pequena (una fila por
cambio de tesis persistido).

Desplegada en produccion el 2026-10-31 (confirmado por Nico via piloto).
"""

import sqlalchemy as sa

from alembic import op

revision = "0118_thesis_attention_idx"
down_revision = "0117_fk_child_indexes"
branch_labels = None
depends_on = None

_INDICE = "ix_thesis_changes_tenant_company_id"


def _existe_indice(bind) -> bool:
    return any(
        ix["name"] == _INDICE
        for ix in sa.inspect(bind).get_indexes("thesis_changes")
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _existe_indice(bind):
        return
    op.create_index(
        _INDICE,
        "thesis_changes",
        ["tenant_id", "company_id", "id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _existe_indice(bind):
        return
    op.drop_index(_INDICE, table_name="thesis_changes")
