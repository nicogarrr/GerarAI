"""Columna accession_number en financial_facts (trazabilidad SEC por filing).

Aditiva y nullable: las filas existentes quedan en NULL hasta la proxima
ingesta SEC, que los re-escribe al refrescar (los hechos reportados se
reemplazan en cada refresh). Sin backfill: un accession inventado es peor
que un NULL honesto.
"""
import sqlalchemy as sa

from alembic import op

revision = "0068_financial_facts_accession"
down_revision = "0067_insider_rule_10b5_1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "financial_facts",
        sa.Column("accession_number", sa.String(40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("financial_facts", "accession_number")
