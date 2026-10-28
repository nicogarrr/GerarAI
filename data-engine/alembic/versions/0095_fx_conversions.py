"""Cambios de divisa reales del Flex (libro de divisas).

Tabla nueva y vacia; nada se retro-rellena. Downgrade la elimina.
"""
import sqlalchemy as sa

from alembic import op

revision = "0095_fx_conversions"
down_revision = "0094_paper_trade_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "fx_conversions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "fx_conversions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("disposed_currency", sa.String(10), nullable=False),
        sa.Column("disposed_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("acquired_currency", sa.String(10), nullable=False),
        sa.Column("acquired_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_fx_conversion_tenant_external"),
    )
    op.create_index("ix_fx_conversions_tenant_id", "fx_conversions", ["tenant_id"])
    op.create_index("ix_fx_conversions_trade_date", "fx_conversions", ["trade_date"])


def downgrade() -> None:
    op.drop_table("fx_conversions")
