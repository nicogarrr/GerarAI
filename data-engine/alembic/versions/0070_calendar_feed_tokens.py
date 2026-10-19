"""Tabla calendar_feed_tokens: suscripcion ICS por tenant, solo hash del token (aditiva)."""
import sqlalchemy as sa

from alembic import op

revision = "0070_calendar_feed_tokens"
down_revision = "0069_earnings_dates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_feed_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False, server_default="followed"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_calendar_feed_tokens_tenant_id", "calendar_feed_tokens", ["tenant_id"])
    op.create_index("ix_calendar_feed_tokens_token_hash", "calendar_feed_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_calendar_feed_tokens_token_hash", table_name="calendar_feed_tokens")
    op.drop_index("ix_calendar_feed_tokens_tenant_id", table_name="calendar_feed_tokens")
    op.drop_table("calendar_feed_tokens")
