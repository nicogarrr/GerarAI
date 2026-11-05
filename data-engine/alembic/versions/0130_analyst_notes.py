"""Notas de analista estructuradas (entrada del experto en analistas).

Feature aprobada por Nico (4-nov-2026): el experto en analistas del equipo del
Cerebro recoge solo cada nota publicada (firma, analista, fecha, accion,
rating y objetivo antes -> despues, precio ese dia, argumentos, sentimiento,
cita literal y fuente), mas todo lo que la fuente diga (estimaciones por ano,
metodo de valoracion, supuestos por segmento, casos alcista/bajista,
catalizadores, riesgos, cambios, enlaces) y un JSON ``extras``.

Solo crea una tabla nueva y vacia; nadie la lee hasta que el colector y la API
la usen. Downgrade la elimina. Idempotente si create_all ya la creo.
"""

import sqlalchemy as sa

from alembic import op

revision = "0130_analyst_notes"
down_revision = "0129_value_drivers"
branch_labels = None
depends_on = None

TABLE = "analyst_notes"
ACTIONS = ("initiate", "reiterate", "upgrade", "downgrade", "maintain", "other")
SOURCE_TYPES = ("yahoo_upgrades_downgrades", "news", "press", "social", "other")
SENTIMENTS = ("positive", "neutral", "negative")
VERIFICATIONS = ("verificado", "fragmento", "rumor_no_verificado")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("firm", sa.String(200), nullable=False),
        sa.Column("firm_key", sa.String(200), nullable=False),
        sa.Column("analyst", sa.String(200), nullable=True),
        sa.Column("note_date", sa.Date(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("rating_old", sa.String(80), nullable=True),
        sa.Column("rating_new", sa.String(80), nullable=True),
        sa.Column("pt_old", sa.Numeric(24, 8), nullable=True),
        sa.Column("pt_new", sa.Numeric(24, 8), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("price_at_note", sa.Numeric(24, 8), nullable=True),
        sa.Column("key_arguments", sa.JSON(), nullable=False),
        sa.Column("sentiment", sa.String(10), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("verification", sa.String(30), nullable=False),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("estimates", sa.JSON(), nullable=False),
        sa.Column("valuation", sa.JSON(), nullable=False),
        sa.Column("segment_assumptions", sa.JSON(), nullable=False),
        sa.Column("bull_target", sa.Numeric(24, 8), nullable=True),
        sa.Column("bear_target", sa.Numeric(24, 8), nullable=True),
        sa.Column("bull_case", sa.Text(), nullable=True),
        sa.Column("bear_case", sa.Text(), nullable=True),
        sa.Column("catalysts", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("changes_since_previous", sa.Text(), nullable=True),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("extras", sa.JSON(), nullable=False),
        sa.Column("driver_refs", sa.JSON(), nullable=True),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_in_list("action", ACTIONS), name="ck_analyst_note_action"),
        sa.CheckConstraint(_in_list("source_type", SOURCE_TYPES), name="ck_analyst_note_source_type"),
        sa.CheckConstraint(
            "sentiment IS NULL OR " + _in_list("sentiment", SENTIMENTS),
            name="ck_analyst_note_sentiment",
        ),
        sa.CheckConstraint(_in_list("verification", VERIFICATIONS), name="ck_analyst_note_verification"),
        sa.UniqueConstraint("dedupe_key", name="uq_analyst_notes_dedupe_key"),
    )
    op.create_index("ix_analyst_notes_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_analyst_notes_company_id", TABLE, ["company_id"])
    op.create_index("ix_analyst_notes_ticker", TABLE, ["ticker"])


def downgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(TABLE)
