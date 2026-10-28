"""Supuesto de coste persistido por trade del paper book (comision + spread).

Las columnas nuevas son NULL en los trades existentes: un historico sin
supuesto persistido nunca se retro-rellena y su neto queda N/D. El downgrade
retira solo los metadatos de coste y conserva cada trade.
"""
import sqlalchemy as sa

from alembic import op

revision = "0093_paper_trade_costs"
down_revision = "0092_schedule_13dg_filings"
branch_labels = None
depends_on = None

_NEW = {
    "entry_fee": sa.Column("entry_fee", sa.Numeric(20, 6), nullable=True),
    "exit_fee": sa.Column("exit_fee", sa.Numeric(20, 6), nullable=True),
    "cost_assumption_version": sa.Column("cost_assumption_version", sa.String(80), nullable=True),
}


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("paper_trades")}
    for name, column in _NEW.items():
        if name not in columns:
            op.add_column("paper_trades", column)


def downgrade() -> None:
    with op.batch_alter_table("paper_trades") as batch:
        for name in _NEW:
            batch.drop_column(name)
