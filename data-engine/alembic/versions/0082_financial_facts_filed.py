"""Columna filed en financial_facts: fecha de presentacion del filing (point-in-time).

Aditiva y nullable. ``filed`` es la fecha en que la SEC publico el filing del
que sale la cifra guardada (campo ``filed`` de companyfacts). Con ella una
reconstruccion historica (``as_of`` pasado) puede descartar cifras que aun no
eran publicas en esa fecha, en vez de fiarse solo del ejercicio fiscal.

Sin backfill: las filas existentes quedan en NULL hasta la proxima ingesta SEC,
que reescribe los hechos reportados en cada refresh. Mientras sea NULL, el
lector aplica un retraso conservador sobre el cierre del periodo. Una fecha
inventada es peor que un NULL honesto.
"""
import sqlalchemy as sa

from alembic import op

revision = "0082_financial_facts_filed"
down_revision = "0081_tenant_llm_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financial_facts", sa.Column("filed", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_facts", "filed")
