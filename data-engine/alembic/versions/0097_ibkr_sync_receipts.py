"""Durable, credential-free tenant IBKR sync receipts."""
import sqlalchemy as sa

from alembic import op

revision = "0097_ibkr_sync_receipts"
down_revision = "0096_ibkr_raw_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # init_db can create models before Alembic adopts the revision.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("ibkr_sync_receipts"):
        from app.models.ibkr_connection import IBKRSyncReceipt
        columns = {c["name"]: c for c in inspector.get_columns("ibkr_sync_receipts")}
        expected = IBKRSyncReceipt.__table__.columns
        if set(columns) != set(expected.keys()):
            raise RuntimeError("ibkr_sync_receipts schema mismatch")
        for name, column in columns.items():
            target = expected[name]
            if column["nullable"] != target.nullable or column["type"]._type_affinity != target.type._type_affinity:
                raise RuntimeError("ibkr_sync_receipts schema mismatch")
            if isinstance(target.type, sa.String) and getattr(column["type"], "length", None) != target.type.length:
                raise RuntimeError("ibkr_sync_receipts schema mismatch")
        return
    op.create_table(
        "ibkr_sync_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(40)),
    )
    op.create_index("ix_ibkr_sync_receipts_tenant_id", "ibkr_sync_receipts", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("ibkr_sync_receipts")
