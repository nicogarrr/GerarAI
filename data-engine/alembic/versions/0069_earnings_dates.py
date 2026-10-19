"""Tabla earnings_dates: proximas fechas de resultados por ticker (aditiva)."""
import sqlalchemy as sa

from alembic import op

revision = "0069_earnings_dates"
down_revision = "0068_financial_facts_accession"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "earnings_dates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("session", sa.String(20), nullable=True),
        sa.Column("fiscal_label", sa.String(40), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_label", sa.String(160), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "event_date", "source", name="uq_earnings_date_ticker_day_source"),
    )
    op.create_index("ix_earnings_dates_ticker", "earnings_dates", ["ticker"])
    op.create_index("ix_earnings_dates_event_date", "earnings_dates", ["event_date"])


def downgrade() -> None:
    op.drop_index("ix_earnings_dates_event_date", table_name="earnings_dates")
    op.drop_index("ix_earnings_dates_ticker", table_name="earnings_dates")
    op.drop_table("earnings_dates")
