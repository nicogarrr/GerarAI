"""Columna invalidation_rules en thesis_versions: criterios medibles de invalidacion.

Aditiva y nullable. ``invalidation_criteria`` sigue siendo el texto libre de
siempre; ``invalidation_rules`` guarda criterios opcionales y evaluables
(metrica, operador, umbral, descripcion) que el evaluador de alertas comprueba
para avisar cuando la tesis queda invalidada.

Cadena: 0084 de biblioteca ya esta en main; 0083 de DCA sigue aislada.
No se renombra ninguna revision aplicada.
Sin backfill: las tesis existentes quedan en NULL (sin criterios medibles).
"""
import sqlalchemy as sa

from alembic import op

revision = "0085_thesis_invalidation_rules"
down_revision = "0084_knowledge_document_ticker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("thesis_versions", sa.Column("invalidation_rules", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("thesis_versions", "invalidation_rules")
