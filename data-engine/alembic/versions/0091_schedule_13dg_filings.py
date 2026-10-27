"""SC 13D/13G filings table (titulares >5%, fuente primaria SEC EDGAR).

Una fila inmutable por (tenant, accession); las enmiendas son filas propias.
Los campos no parseados quedan NULL (N/D en la UI, nunca inventados).
Downgrade elimina solo esta tabla.
"""
import sqlalchemy as sa

from alembic import op

revision = "0091_schedule_13dg_filings"
down_revision = "0090_paper_proposal_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("schedule_13dg_filings"):
        # create_all pudo correr primero: adoptar solo un esquema identico.
        from app.models.entities import Schedule13DGFiling

        inspector = sa.inspect(op.get_bind())
        columns = {c["name"]: c for c in inspector.get_columns("schedule_13dg_filings")}
        expected = Schedule13DGFiling.__table__.columns
        if set(columns) != set(expected.keys()):
            raise RuntimeError("schedule_13dg_filings schema mismatch")
        for name, column in columns.items():
            target = expected[name]
            if column["nullable"] != target.nullable or column["type"]._type_affinity != target.type._type_affinity:
                raise RuntimeError("schedule_13dg_filings schema mismatch")
            if isinstance(target.type, sa.String) and getattr(column["type"], "length", None) != target.type.length:
                raise RuntimeError("schedule_13dg_filings schema mismatch")
        return
    op.create_table(
        "schedule_13dg_filings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("accession_number", sa.String(40), nullable=False),
        sa.Column("form", sa.String(30), nullable=False),
        sa.Column("is_amendment", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("issuer_cik", sa.String(20), nullable=False),
        sa.Column("issuer_ticker", sa.String(20), nullable=True),
        sa.Column("issuer_name", sa.String(300), nullable=True),
        sa.Column("filer_cik", sa.String(20), nullable=True),
        sa.Column("holder_name", sa.String(300), nullable=True),
        sa.Column("aggregate_shares", sa.Float(), nullable=True),
        sa.Column("percent_of_class", sa.Float(), nullable=True),
        sa.Column("sole_voting_power", sa.Float(), nullable=True),
        sa.Column("shared_voting_power", sa.Float(), nullable=True),
        sa.Column("sole_dispositive_power", sa.Float(), nullable=True),
        sa.Column("shared_dispositive_power", sa.Float(), nullable=True),
        sa.Column("holders", sa.JSON(), nullable=False),
        sa.Column("securities_class_title", sa.String(160), nullable=True),
        sa.Column("snapshot_date", sa.String(20), nullable=True),
        sa.Column("filing_date", sa.String(20), nullable=True),
        sa.Column("report_date", sa.String(20), nullable=True),
        sa.Column("signature_date", sa.String(20), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("index_url", sa.String(1000), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("parser_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="parsed"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "accession_number", name="uq_schedule13dg_tenant_accession"),
        sa.Index("ix_schedule13dg_issuer", "issuer_cik"),
        sa.Index("ix_schedule13dg_ticker", "issuer_ticker"),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("schedule_13dg_filings"):
        op.drop_table("schedule_13dg_filings")
