"""Veredictos del LLM revisor de ProPicks (calibracion Brier)."""
import sqlalchemy as sa

from alembic import op

revision = "0065_propick_reviews"
down_revision = "0064_propick_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "propick_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("model", sa.String(160), nullable=True),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("base_score", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("price_date", sa.Date(), nullable=True),
        sa.Column("verdict", sa.JSON(), nullable=False),
        sa.Column("outcome_return", sa.Float(), nullable=True),
        sa.Column("outcome_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_propick_reviews_tenant_id", "propick_reviews", ["tenant_id"])
    op.create_index("ix_propick_reviews_ticker", "propick_reviews", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_propick_reviews_ticker", table_name="propick_reviews")
    op.drop_index("ix_propick_reviews_tenant_id", table_name="propick_reviews")
    op.drop_table("propick_reviews")
