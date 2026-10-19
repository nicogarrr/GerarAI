"""Tabla global etf_holdings (holdings oficiales de ETFs tematicos). Aditiva."""
import sqlalchemy as sa

from alembic import op

revision = "0075_etf_holdings"
down_revision = "0074_news_generic_titles_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "etf_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("etf", sa.String(12), nullable=False),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("weight_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.UniqueConstraint("etf", "ticker", name="uq_etf_holding"),
    )
    op.create_index("ix_etf_holdings_etf", "etf_holdings", ["etf"])
    op.create_index("ix_etf_holdings_ticker", "etf_holdings", ["ticker"])


def downgrade() -> None:
    op.drop_table("etf_holdings")
