"""Inputs declarados por empresa para modelos sin datos (pre-ingresos, escenarios, red).

Feature aprobada por Nico (4-nov-2026): el Cerebro rellena solo los inputs que
le faltan al modelo declarado de una empresa (suscriptores, penetracion, ARPU,
reparto, satelites...). Cada valor guarda su rango bajo/base/alto, su unidad,
su estado (oficial/estimado/derivado/supuesto_por_defecto/manual), el metodo
que lo produjo (extract/infer/derive/default/manual/analyst), la fuente con
URL y cita, y la fecha. Las revisiones no se sobrescriben: la fila vigente es
la de ``superseded_at IS NULL`` (una por tenant, empresa, input y segmento).

Solo crea una tabla nueva y vacia; nadie la lee hasta que el servicio y el
motor la consuman. Downgrade la elimina. Idempotente si create_all ya la creo.
"""

import sqlalchemy as sa

from alembic import op

revision = "0127_declared_input_values"
down_revision = "0126_email_user_prefs"
branch_labels = None
depends_on = None

TABLE = "declared_input_values"
STATUSES = ("oficial", "estimado", "derivado", "supuesto_por_defecto", "manual")
METHODS = ("extract", "infer", "derive", "default", "manual", "analyst")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("input_key", sa.String(120), nullable=False),
        sa.Column("segment_key", sa.String(80), nullable=False, server_default=""),
        sa.Column("low", sa.Numeric(24, 8), nullable=True),
        sa.Column("base", sa.Numeric(24, 8), nullable=False),
        sa.Column("high", sa.Numeric(24, 8), nullable=True),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("analyst_firm", sa.String(160), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("model_family", sa.String(80), nullable=True),
        sa.Column("input_set_version", sa.String(40), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_declared_input_status"),
        sa.CheckConstraint(_in_list("method", METHODS), name="ck_declared_input_method"),
    )
    op.create_index("ix_declared_input_values_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_declared_input_values_company_id", TABLE, ["company_id"])
    op.create_index(
        "uq_declared_input_current",
        TABLE,
        ["tenant_id", "company_id", "input_key", "segment_key"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
        sqlite_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(TABLE)
