"""positions: valuacion en suspenso (valuation_hold_*), NULL = sin suspension.

Aditiva y reversible (DROP COLUMN). Sin backfill: ninguna posicion existente
queda suspendida por la migracion. Un downgrade en prod con posiciones ya
suspendidas perderia el motivo y la fecha: iria aparte, con backup restorable.
"""
import sqlalchemy as sa

from alembic import op

revision = "0078_position_valuation_hold"
down_revision = "0077_plan_monthly_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("valuation_hold_reason", sa.String(200), nullable=True))
    op.add_column("positions", sa.Column("valuation_hold_effective_date", sa.Date(), nullable=True))
    op.add_column("positions", sa.Column("valuation_hold_since", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "valuation_hold_since")
    op.drop_column("positions", "valuation_hold_effective_date")
    op.drop_column("positions", "valuation_hold_reason")
