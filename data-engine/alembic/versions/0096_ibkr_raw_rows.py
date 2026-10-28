"""Filas crudas del Flex de IBKR (todos los atributos, aunque aun no se usen).

Tabla nueva y vacia; nada se retro-rellena. Downgrade la elimina.
"""
import sqlalchemy as sa

from alembic import op

revision = "0096_ibkr_raw_rows"
down_revision = "0095_fx_conversions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "ibkr_raw_rows" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "ibkr_raw_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("account_id", sa.String(40), nullable=True),
        sa.Column("section", sa.String(80), nullable=False),
        sa.Column("path", sa.String(200), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "row_hash", name="uq_ibkr_raw_row_tenant_hash"),
    )
    op.create_index("ix_ibkr_raw_rows_tenant_id", "ibkr_raw_rows", ["tenant_id"])
    op.create_index("ix_ibkr_raw_rows_section", "ibkr_raw_rows", ["section"])


def downgrade() -> None:
    op.drop_table("ibkr_raw_rows")
