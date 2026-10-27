"""Encrypted reporting-only Flex connection per tenant."""
import sqlalchemy as sa

from alembic import op

revision = "0089_ibkr_connections"
down_revision = "0088_inferred_input_tenant_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ibkr_connections"):
        # create_all may have run first. Adopt only an identical schema.
        from app.models.ibkr_connection import IBKRConnection
        inspector = sa.inspect(op.get_bind())
        columns = {c["name"]: c for c in inspector.get_columns("ibkr_connections")}
        expected = IBKRConnection.__table__.columns
        if set(columns) != set(expected.keys()):
            raise RuntimeError("ibkr_connections schema mismatch")
        for name, column in columns.items():
            target = expected[name]
            if column["nullable"] != target.nullable or column["type"]._type_affinity != target.type._type_affinity:
                raise RuntimeError("ibkr_connections schema mismatch")
            if isinstance(target.type, sa.String) and getattr(column["type"], "length", None) != target.type.length:
                raise RuntimeError("ibkr_connections schema mismatch")
        if not any(c["column_names"] == ["tenant_id"] for c in inspector.get_unique_constraints("ibkr_connections")):
            raise RuntimeError("ibkr_connections tenant uniqueness missing")
        return
    op.create_table(
        "ibkr_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_ciphertext", sa.Text(), nullable=True),
        sa.Column("query_id", sa.String(32), nullable=False),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("complete_query", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("statement_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_ibkr_connection_tenant"),
    )
    op.create_index("ix_ibkr_connections_tenant_id", "ibkr_connections", ["tenant_id"])


def downgrade() -> None:
    # Financial connection history is deliberately retained on rollback.
    # It contains no plaintext token, and an older application ignores it.
    pass
