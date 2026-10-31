"""Add database CHECK constraints for non-negative values.

Revision ID: 0108_add_db_check_constraints
Revises: 0107_add_fk_cascades
Create Date: 2026-10-30T22:30:00.000Z

Adds CHECK constraints to ensure financial data integrity:
- transactions.quantity >= 0 (ck_transactions_quantity_non_negative)
- transactions.price >= 0 en patas buy/sell; las acciones de caja admiten
  signo (ck_transactions_price_non_negative)
- transactions.fees >= 0 (ck_transactions_fees_non_negative)
- positions.quantity >= 0 (ck_positions_quantity_non_negative)
- market_prices.close >= 0 (ck_market_prices_close_non_negative)

Predicado de price nacido ya en su forma final: MEDIDO en prod
(2026-10-31, BD en 0103) hay 74 transactions con price < 0 legitimas
(fee 8, interest 30, withholding 36; ninguna quantity/fees negativa). IBKR
Flex entrega esas retenciones como CashTransactions con importe NEGATIVO y el
importador guarda el signo porque el XIRR lo usa. Un ``price >= 0`` plano
abortaria el upgrade aqui mismo; 0111 ya no necesita rehacer este CHECK.

Fulfills: VAL-DB-003, VAL-DB-008
"""

from alembic import op

revision = "0108_add_db_check_constraints"
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
            "price >= 0 OR action NOT IN ('buy', 'sell')",
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

