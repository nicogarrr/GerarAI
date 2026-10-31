"""Narrow transactions price CHECK to trade legs only.

Revision ID: 0110_price_check_cash_actions
Revises: 0109_add_audit_log_table
Create Date: 2026-10-31T00:38:00.000Z

VAL-DB-003 added ``transactions.price >= 0`` for every action, but IBKR Flex
delivers withholding tax and other fees as CashTransactions with NEGATIVE
amounts (money out), and the importer stores the sign because the XIRR/outflow
math depends on it. Every real retention import failed with
``ck_transactions_price_non_negative``. The constraint now guards only the
buy/sell legs, where a negative price is always invalid.
"""

from alembic import op

revision = "0110_price_check_cash_actions"
down_revision = "0109_add_audit_log_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint("ck_transactions_price_non_negative", type_="check")
        batch_op.create_check_constraint(
            "ck_transactions_price_non_negative",
            "price >= 0 OR action NOT IN ('buy', 'sell')",
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint("ck_transactions_price_non_negative", type_="check")
        batch_op.create_check_constraint(
            "ck_transactions_price_non_negative",
            "price >= 0",
        )
