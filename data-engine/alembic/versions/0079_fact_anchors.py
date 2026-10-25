"""Tabla fact_anchors: anclas de dato con provenance verificada (aditiva).

Reproduce exactamente `FactAnchor` (entities.py): columnas, nullability, los
tres indices implicados/declarados y el unique tenant-scoped. Las FK van sin
ON DELETE, igual que el mixin `TenantOwnedMixin` y el propio modelo. El
append-only se garantiza en el ORM (eventos before_update/before_delete y DML
masivo), no con triggers de base de datos.
"""
import sqlalchemy as sa

from alembic import op

revision = "0079_fact_anchors"
down_revision = "0078_position_valuation_hold"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fact_anchors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accession_number", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("field", sa.String(80), nullable=False),
        sa.Column("value_text", sa.String(2000), nullable=False),
        sa.Column("label", sa.String(10), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_offset", sa.Integer(), nullable=False),
        sa.Column("item", sa.String(40), nullable=True),
        sa.Column("extractor", sa.String(120), nullable=False),
        sa.Column("derivation", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "accession_number",
            "filename",
            "field",
            "quote_offset",
            "body_sha256",
            name="uq_fact_anchors_tenant_point",
        ),
    )
    op.create_index("ix_fact_anchors_tenant_id", "fact_anchors", ["tenant_id"])
    op.create_index("ix_fact_anchors_accession_number", "fact_anchors", ["accession_number"])
    op.create_index("ix_fact_anchors_company", "fact_anchors", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_fact_anchors_company", table_name="fact_anchors")
    op.drop_index("ix_fact_anchors_accession_number", table_name="fact_anchors")
    op.drop_index("ix_fact_anchors_tenant_id", table_name="fact_anchors")
    op.drop_table("fact_anchors")
