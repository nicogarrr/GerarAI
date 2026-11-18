"""Avisos SEC Form 144 (venta PROPUESTA, Rule 144), fuente primaria EDGAR.

Una fila inmutable por (tenant, accession); las enmiendas (144/A) son filas
propias. Los campos no parseados quedan NULL (N/D en la UI, nunca
inventados). Un Form 144 es un aviso de venta propuesta, nunca una venta
ejecutada: no escribe en insider_filings / insider_transactions.
Downgrade elimina solo esta tabla.

Adopcion: si la tabla ya existe (un create_all corrio primero), NO basta con
comparar columnas: un DDL sin constraints no lanza y dejaria la tabla sin la
UNIQUE(tenant, accession) que hace idempotente la ingesta, sin la FK tenant
y sin los indices de lectura. Se validan PK/FK/unique/indices y se crea lo
que falte de forma segura (batch para constraints, portable SQLite/Postgres);
una PK ausente o columnas divergentes son un esquema ajeno y FALLAN.

Downgrade no destructivo (decisión, auditoría FAV 2026-11-18): una tabla
ADOPTADA no la creó la migración, así que el downgrade NO la borra jamás
(borrarla destruiría filas previas ajenas a esta migración). Para poder
distinguir ambos casos de forma portable (SQLite/Postgres), el upgrade
registra en la tabla auxiliar migration_table_provenance si la tabla fue
"created" por esta migración o "adopted" (pre-existente); el downgrade solo
elimina form144_notices cuando consta "created". Sin marca (migración
antigua): se conserva la tabla (lo seguro) y no se toca nada.
"""
import sqlalchemy as sa

from alembic import op

revision = "0137_form144_notices"
down_revision = "0136_peer_rank_inputs"
branch_labels = None
depends_on = None

_TABLE = "form144_notices"
_UNIQUE_NAME = "uq_form144_tenant_accession"
_FK_NAME = "fk_form144_tenant_id"
_INDEXES = {
    # El modelo hereda tenant_id de TenantOwnedMixin con index=True: su indice
    # se llama ix_form144_notices_tenant_id y la migracion tambien lo crea.
    "ix_form144_notices_tenant_id": ["tenant_id"],
    "ix_form144_issuer": ["issuer_cik"],
    "ix_form144_tenant_ticker_date": ["tenant_id", "issuer_ticker", "filing_date"],
}


def _check_columns(inspector) -> None:
    from app.models.entities import Form144Notice

    columns = {c["name"]: c for c in inspector.get_columns(_TABLE)}
    expected = Form144Notice.__table__.columns
    if set(columns) != set(expected.keys()):
        raise RuntimeError("form144_notices schema mismatch")
    for name, column in columns.items():
        target = expected[name]
        if column["nullable"] != target.nullable or column["type"]._type_affinity != target.type._type_affinity:
            raise RuntimeError("form144_notices schema mismatch")
        if isinstance(target.type, sa.String) and getattr(column["type"], "length", None) != target.type.length:
            raise RuntimeError("form144_notices schema mismatch")


def _ensure_constraints_and_indexes(inspector) -> None:
    """Valida PK y crea UNIQUE/FK/indices ausentes en una tabla pre-creada."""
    pk = inspector.get_pk_constraint(_TABLE) or {}
    if "id" not in (pk.get("constrained_columns") or []):
        raise RuntimeError("form144_notices sin PK en id: esquema ajeno")
    has_unique = any(
        set(uq.get("column_names") or []) == {"tenant_id", "accession_number"}
        for uq in inspector.get_unique_constraints(_TABLE)
    )
    fks_tenant = [
        fk
        for fk in inspector.get_foreign_keys(_TABLE)
        if "tenant_id" in (fk.get("constrained_columns") or [])
    ]
    for fk in fks_tenant:
        # No basta tabla y columna local: una FK tenant_id apuntando a otra
        # tabla o columna referenciada es un esquema ajeno y FALLA.
        if fk.get("referred_table") != "tenants" or fk.get("referred_columns") != ["id"]:
            raise RuntimeError("form144_notices FK tenant ajena: esquema incompatible")
    has_fk = bool(fks_tenant)
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


_PROVENANCE_TABLE = "migration_table_provenance"


def _provenance_mode(inspector, bind) -> str | None:
    if not inspector.has_table(_PROVENANCE_TABLE):
        return None
    row = bind.execute(
        sa.text(
            f"SELECT mode FROM {_PROVENANCE_TABLE} "  # noqa: S608 - identificadores propios constantes
            "WHERE revision = :revision AND table_name = :table"
        ),
        {"revision": revision, "table": _TABLE},
    ).first()
    return row[0] if row else None


def _record_provenance(bind, mode: str) -> None:
    if not sa.inspect(bind).has_table(_PROVENANCE_TABLE):
        op.create_table(
            _PROVENANCE_TABLE,
            sa.Column("revision", sa.String(40), primary_key=True),
            sa.Column("table_name", sa.String(120), primary_key=True),
            sa.Column("mode", sa.String(10), nullable=False),
        )
    bind.execute(
        sa.text(
            f"INSERT INTO {_PROVENANCE_TABLE} (revision, table_name, mode) "  # noqa: S608
            "VALUES (:revision, :table, :mode)"
        ),
        {"revision": revision, "table": _TABLE, "mode": mode},
    )


def _drop_provenance(bind) -> None:
    if sa.inspect(bind).has_table(_PROVENANCE_TABLE):
        bind.execute(
            sa.text(
                f"DELETE FROM {_PROVENANCE_TABLE} "  # noqa: S608
                "WHERE revision = :revision AND table_name = :table"
            ),
            {"revision": revision, "table": _TABLE},
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(_TABLE):
        _check_columns(inspector)
        _ensure_constraints_and_indexes(inspector)
        # Solo se marca "adopted" la primera vez: si una corrida previa ya la
        # creó la migración, la marca "created" manda y se conserva.
        if _provenance_mode(inspector, bind) is None:
            _record_provenance(bind, "adopted")
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("accession_number", sa.String(40), nullable=False),
        sa.Column("form", sa.String(10), nullable=False),
        sa.Column("is_amendment", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("issuer_cik", sa.String(20), nullable=False),
        sa.Column("issuer_ticker", sa.String(20), nullable=True),
        sa.Column("issuer_name", sa.String(300), nullable=True),
        sa.Column("seller_cik", sa.String(20), nullable=True),
        sa.Column("seller_name", sa.String(300), nullable=True),
        sa.Column("relationships", sa.JSON(), nullable=False),
        sa.Column("broker_name", sa.String(300), nullable=True),
        sa.Column("securities_class_title", sa.String(160), nullable=True),
        sa.Column("shares_to_sell", sa.Float(), nullable=True),
        sa.Column("aggregate_market_value", sa.Float(), nullable=True),
        sa.Column("shares_outstanding", sa.Float(), nullable=True),
        sa.Column("approx_sale_date", sa.String(20), nullable=True),
        sa.Column("exchange", sa.String(60), nullable=True),
        sa.Column("securities", sa.JSON(), nullable=False),
        sa.Column("acquisitions", sa.JSON(), nullable=False),
        sa.Column("sales_past_3m", sa.JSON(), nullable=False),
        sa.Column("nothing_to_report_past_3m", sa.Boolean(), nullable=True),
        sa.Column("notice_date", sa.String(20), nullable=True),
        sa.Column("plan_adoption_dates", sa.JSON(), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("filing_date", sa.String(20), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("index_url", sa.String(1000), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("parser_version", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="parsed"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "accession_number", name="uq_form144_tenant_accession"),
        sa.Index("ix_form144_notices_tenant_id", "tenant_id"),
        sa.Index("ix_form144_issuer", "issuer_cik"),
        sa.Index("ix_form144_tenant_ticker_date", "tenant_id", "issuer_ticker", "filing_date"),
    )


    _record_provenance(bind, "created")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    mode = _provenance_mode(inspector, bind)
    if mode == "created":
        # La migración creó la tabla: el downgrade la retira.
        if inspector.has_table(_TABLE):
            op.drop_table(_TABLE)
    # mode "adopted" o sin marca: la tabla NO la creó la migración (o no
    # consta) y el downgrade la conserva con sus filas (no destructivo).
    _drop_provenance(bind)
