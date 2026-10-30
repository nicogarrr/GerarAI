"""Add database CHECK constraints for non-negative values.

Revision ID: 0108_add_database_check_constraints
Revises: 0107_add_fk_cascades
Create Date: 2026-10-30T22:30:00.000Z

Adds CHECK constraints to ensure financial data integrity:
- transactions.quantity >= 0 (ck_transactions_quantity_non_negative)
- transactions.price >= 0 (ck_transactions_price_non_negative)
- transactions.fees >= 0 (ck_transactions_fees_non_negative)
- positions.quantity >= 0 (ck_positions_quantity_non_negative)
- market_prices.close >= 0 (ck_market_prices_close_non_negative)

Fulfills: VAL-DB-003, VAL-DB-008
"""

from alembic import op

revision = "0108_add_database_check_constraints"
down_revision = "0107_add_fk_cascades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # transactions
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_transactions_quantity_non_negative",
            "quantity >= 0",
        )
        batch_op.create_check_constraint(
            "ck_transactions_price_non_negative",
            "price >= 0",
        )
        batch_op.create_check_constraint(
            "ck_transactions_fees_non_negative",
            "fees >= 0",
        )

    # positions
    with op.batch_alter_table("positions", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_positions_quantity_non_negative",
            "quantity >= 0",
        )

    # market_prices
    with op.batch_alter_table("market_prices", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_market_prices_close_non_negative",
            "close >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("market_prices", schema=None) as batch_op:
        batch_op.drop_constraint("ck_market_prices_close_non_negative", type_="check")

    with op.batch_alter_table("positions", schema=None) as batch_op:
        batch_op.drop_constraint("ck_positions_quantity_non_negative", type_="check")

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint("ck_transactions_fees_non_negative", type_="check")
        batch_op.drop_constraint("ck_transactions_price_non_negative", type_="check")
        batch_op.drop_constraint("ck_transactions_quantity_non_negative", type_="check")

