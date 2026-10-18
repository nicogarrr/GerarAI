"""Serie diaria del benchmark SPY (fuera del master de empresas)."""
import sqlalchemy as sa

from alembic import op

revision = "0066_benchmark_prices"
down_revision = "0065_propick_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "benchmark_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("adj_close", sa.Numeric(20, 6), nullable=True),
        sa.Column("source", sa.String(80), nullable=False, server_default="yfinance"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "date", name="uq_benchmark_price_symbol_date"),
    )
    op.create_index("ix_benchmark_prices_symbol", "benchmark_prices", ["symbol"])
    op.create_index("ix_benchmark_prices_date", "benchmark_prices", ["date"])


def downgrade() -> None:
    op.drop_index("ix_benchmark_prices_date", table_name="benchmark_prices")
    op.drop_index("ix_benchmark_prices_symbol", table_name="benchmark_prices")
    op.drop_table("benchmark_prices")
