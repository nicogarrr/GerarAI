"""Inventario de impulsores de valor por empresa (etapa «Recopilador» del equipo de expertos).

Feature aprobada por Nico (4-nov-2026): al generar la tesis, el equipo de
expertos lista todo lo que mueve el valor de una empresa (negocios, contratos,
mercados, gobierno, activos, opciones, restricciones, pasivos, catalizadores),
cada pieza con su estado (firmado/anunciado/LOI/regulador/rumor), su economía
pública, su fuente con URL, cita y tipo, y un tratamiento obligatorio
(en_modelo/suelo/opcion/riesgo/no_valorado/pendiente). Las revisiones no se
sobrescriben: la fila vigente es la de ``superseded_at IS NULL`` (una por
tenant, empresa e impulsor).

Solo crea una tabla nueva y vacía; nadie la lee hasta que el servicio y la
tesis la consuman. Downgrade la elimina. Idempotente si create_all ya la creó.
"""

import sqlalchemy as sa

from alembic import op

revision = "0129_value_drivers"
down_revision = "0128_public_market_data"
branch_labels = None
depends_on = None

TABLE = "value_drivers"
CATEGORIES = (
    "linea_negocio",
    "contrato",
    "geografia",
    "gobierno",
    "activo",
    "opcion",
    "restriccion",
    "pasivo",
    "catalizador",
)
STATUSES = ("firmado", "anunciado_oficial", "loi_mou", "regulatorio_pendiente", "rumor")
SOURCE_TYPES = ("filing", "nota_empresa", "nota_socio", "regulador", "prensa", "analista", "foro", "redes")
EVIDENCE = ("oficial", "estimado", "rumor")
TREATMENTS = ("en_modelo", "suelo", "opcion", "riesgo", "no_valorado", "pendiente")


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
        sa.Column("driver_key", sa.String(120), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("economics", sa.JSON(), nullable=False),
        sa.Column("timing", sa.String(120), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence", sa.String(20), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("headline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("treatment", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("model_link", sa.String(120), nullable=True),
        sa.Column("reason_if_not_valued", sa.Text(), nullable=True),
        sa.Column("value_per_share_marginal", sa.Numeric(24, 8), nullable=True),
        sa.Column("confidence", sa.Numeric(6, 4), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in_list("category", CATEGORIES), name="ck_value_driver_category"),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_value_driver_status"),
        sa.CheckConstraint(_in_list("source_type", SOURCE_TYPES), name="ck_value_driver_source_type"),
        sa.CheckConstraint(_in_list("evidence", EVIDENCE), name="ck_value_driver_evidence"),
        sa.CheckConstraint(_in_list("treatment", TREATMENTS), name="ck_value_driver_treatment"),
    )
    op.create_index("ix_value_drivers_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_value_drivers_company_id", TABLE, ["company_id"])
    op.create_index(
        "uq_value_driver_current",
        TABLE,
        ["tenant_id", "company_id", "driver_key"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
        sqlite_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(TABLE)
