"""Dividendos devengados y ajustes por splits del paper book.

Todo NULL en los trades existentes: dividendos no computados y sin historial
de ajustes; nada se retro-rellena. El downgrade retira solo estos metadatos.
"""
import sqlalchemy as sa

from alembic import op

revision = "0094_paper_trade_actions"
down_revision = "0093_paper_trade_costs"
branch_labels = None
depends_on = None

_NEW = {
    "dividends_total": sa.Column("dividends_total", sa.Numeric(20, 6), nullable=True),
    "dividends_count": sa.Column("dividends_count", sa.Integer(), nullable=True),
    "dividends_uncertain": sa.Column("dividends_uncertain", sa.Integer(), nullable=True),
    "dividends_wrong_currency": sa.Column("dividends_wrong_currency", sa.Integer(), nullable=True),
    "dividends_source": sa.Column("dividends_source", sa.String(160), nullable=True),
    "split_adjustments": sa.Column("split_adjustments", sa.Integer(), nullable=True),
    "applied_split_ids": sa.Column("applied_split_ids", sa.String(500), nullable=True),
    "last_corporate_action": sa.Column("last_corporate_action", sa.String(160), nullable=True),
    "corporate_action_warning": sa.Column("corporate_action_warning", sa.String(60), nullable=True),
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
