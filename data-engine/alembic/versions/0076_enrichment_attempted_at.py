"""companies.enrichment_attempted_at: marca de intento de enriquecimiento.

Aditiva. Enfriamiento de /companies/ensure: sin ella, cada ensure de una
ficha con sector Unknown e industria no mapeada llamaba a Finnhub otra vez,
para siempre.
"""
import sqlalchemy as sa

from alembic import op

revision = "0076_enrichment_attempted_at"
down_revision = "0075_etf_holdings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("enrichment_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("companies", "enrichment_attempted_at")
