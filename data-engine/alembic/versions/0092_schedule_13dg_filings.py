"""SC 13D/13G filings table (titulares >5%, fuente primaria SEC EDGAR).

Una fila inmutable por (tenant, accession); las enmiendas son filas propias.
Los campos no parseados quedan NULL (N/D en la UI, nunca inventados).
Downgrade elimina solo esta tabla.

Adopcion: si la tabla ya existe (un create_all corrio primero), NO basta con
comparar columnas: un DDL sin constraints no lanza y dejaria la tabla sin la
UNIQUE(tenant, accession) que hace idempotente la ingesta, sin la FK tenant
y sin los indices de lectura. Se validan PK/FK/unique/indices y se crea lo
que falte de forma segura (batch para constraints, portable SQLite/Postgres);
una PK ausente o columnas divergentes son un esquema ajeno y FALLAN.
"""
import sqlalchemy as sa

from alembic import op

revision = "0092_schedule_13dg_filings"
down_revision = "0091_dca_evaluation_runs"
branch_labels = None
depends_on = None

_TABLE = "schedule_13dg_filings"
_UNIQUE_NAME = "uq_schedule13dg_tenant_accession"
_FK_NAME = "fk_schedule13dg_tenant_id"
_INDEXES = {
    "ix_schedule13dg_issuer": ["issuer_cik"],
    "ix_schedule13dg_ticker": ["issuer_ticker"],
}


def _check_columns(inspector) -> None:
    from app.models.entities import Schedule13DGFiling

    columns = {c["name"]: c for c in inspector.get_columns(_TABLE)}
    expected = Schedule13DGFiling.__table__.columns
    if set(columns) != set(expected.keys()):
        raise RuntimeError("schedule_13dg_filings schema mismatch")
    for name, column in columns.items():
        target = expected[name]
        if column["nullable"] != target.nullable or column["type"]._type_affinity != target.type._type_affinity:
            raise RuntimeError("schedule_13dg_filings schema mismatch")
        if isinstance(target.type, sa.String) and getattr(column["type"], "length", None) != target.type.length:
            raise RuntimeError("schedule_13dg_filings schema mismatch")


def _ensure_constraints_and_indexes(inspector) -> None:
    """Valida PK y crea UNIQUE/FK/indices ausentes en una tabla pre-creada."""
    pk = inspector.get_pk_constraint(_TABLE) or {}
    if "id" not in (pk.get("constrained_columns") or []):
        raise RuntimeError("schedule_13dg_filings schema mismatch")

    has_unique = any(
        set(c.get("column_names") or []) == {"tenant_id", "accession_number"}
        for c in inspector.get_unique_constraints(_TABLE)
    )
    has_fk = any(
        fk.get("referred_table") == "tenants"
        and "tenant_id" in (fk.get("constrained_columns") or [])
        for fk in inspector.get_foreign_keys(_TABLE)
    )
    if not has_unique or not has_fk:
        # batch: en SQLite recrea la tabla (conservando datos); en Postgres
        # emite los ALTER TABLE equivalentes. Si los datos existentes violan
        # la UNIQUE, la creacion falla en voz alta en vez de adoptar a medias.
        with op.batch_alter_table(_TABLE) as batch:
            if not has_unique:
                batch.create_unique_constraint(_UNIQUE_NAME, ["tenant_id", "accession_number"])
            if not has_fk:
                batch.create_foreign_key(_FK_NAME, "tenants", ["tenant_id"], ["id"])

    # Tras un posible batch-recreate (SQLite pierde los indices al recrear),
    # se relee y se crea cualquier indice que falte.
    existing = {
        tuple(i.get("column_names") or []) for i in sa.inspect(op.get_bind()).get_indexes(_TABLE)
    }
    for name, columns in _INDEXES.items():
        if tuple(columns) not in existing:
            op.create_index(name, _TABLE, columns)


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(_TABLE):
        _check_columns(sa.inspect(op.get_bind()))
        _ensure_constraints_and_indexes(sa.inspect(op.get_bind()))
        return
    op.create_table(
        _TABLE,
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
    if sa.inspect(op.get_bind()).has_table(_TABLE):
        op.drop_table(_TABLE)
