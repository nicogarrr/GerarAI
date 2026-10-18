"""Snapshots mensuales congelados de ProPicks (point-in-time)."""
import sqlalchemy as sa

from alembic import op

revision = "0064_propick_snapshots"
down_revision = "0063_chat_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "propick_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funnel_version", sa.String(80), nullable=False),
        sa.Column("universe_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "month", name="uq_propick_snapshot_month"),
    )
    op.create_index("ix_propick_snapshots_tenant_id", "propick_snapshots", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_propick_snapshots_tenant_id", table_name="propick_snapshots")
    op.drop_table("propick_snapshots")
