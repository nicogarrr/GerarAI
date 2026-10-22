"""investment_plans.monthly_contribution_currency: divisa de la cuota, NULL legacy.

Aditiva y reversible en dev (DROP COLUMN). El NULL es un estado explicito:
«divisa no registrada». No hay backfill: la etiqueta «€» del formulario no
autentica que TODOS los planes historicos entraran en euros (antes de #288
solo existia el API cruda, sin contrato de divisa). Los totales convertidos
quedan en estado desconocido hasta que el usuario fija la divisa.
"""
import sqlalchemy as sa

from alembic import op

revision = "0077_plan_monthly_currency"
down_revision = "0076_enrichment_attempted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "investment_plans",
        sa.Column("monthly_contribution_currency", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    # Rollback de esquema para dev vacia. Un downgrade prod con divisas ya
    # registradas las perderia: va aparte, con backup restorable.
    op.drop_column("investment_plans", "monthly_contribution_currency")
