"""Registro de intentos de extraccion de candidatos (cerrojo de idempotencia).

Tabla NUEVA (no toca datos existentes). UNIQUE (tenant_id, company_id, source_url): un solo proceso
extrae un activo a la vez. Downgrade = DROP: solo seguro sin datos que conservar; en prod exige backup.
NO aplicada en produccion: requiere ventana/autorizacion aparte.
"""
import sqlalchemy as sa

from alembic import op

revision = "0080_commitment_extraction_attempts"
down_revision = "0079_commitment_checks_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commitment_extraction_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("call_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("outcome", sa.String(80), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_on", sa.Date(), nullable=True),
        sa.Column("next_attempt_on", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bytes_sha256", sa.String(64), nullable=True),
        sa.Column("text_sha256", sa.String(64), nullable=True),
        sa.Column("management_turns", sa.Integer(), nullable=True),
        sa.Column("candidates_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "company_id", "source_url", name="uq_commitment_extraction_attempt"),
    )
    op.create_index("ix_commitment_extraction_attempts_tenant_id", "commitment_extraction_attempts", ["tenant_id"])
    op.create_index("ix_commitment_extraction_attempts_company_id", "commitment_extraction_attempts", ["company_id"])


def downgrade() -> None:
    op.drop_table("commitment_extraction_attempts")
