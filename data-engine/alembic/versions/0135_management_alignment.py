"""Research-only precomputed management alignment; additive, no financial mutations."""
import sqlalchemy as sa

from alembic import op

revision = "0135_management_alignment"
down_revision = "0134_company_delisting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "management_alignment_snapshots" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "management_alignment_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "company_id", name="uq_alignment_tenant_company"),
    )
    op.create_index("ix_management_alignment_snapshots_company_id", "management_alignment_snapshots", ["company_id"])
    op.create_index("ix_management_alignment_snapshots_tenant_id", "management_alignment_snapshots", ["tenant_id"])


def downgrade() -> None:
    if "management_alignment_snapshots" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("management_alignment_snapshots")
