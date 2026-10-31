"""Drop the positions quantity CHECK (shorts are valid domain state).

Revision ID: 0111_price_check_cash_actions
Revises: 0110_drop_dup_portfolio_fks
Create Date: 2026-10-31T00:38:00.000Z

Historia: VAL-DB-003 (0108) nacio exigiendo ``transactions.price >= 0`` para
TODA accion, pero IBKR Flex entrega withholding/fee/interest como
CashTransactions con importe NEGATIVO y el importador guarda el signo porque
el XIRR lo usa. Tras medir prod (74 filas negativas legitimas bloqueando el
upgrade 0103 -> head), el predicado final
``price >= 0 OR action NOT IN ('buy', 'sell')`` se pliega a la propia 0108:
esta migracion ya NO toca el CHECK de price. Lo que queda aqui es el retiro
de ``ck_positions_quantity_non_negative``: el dominio admite cortos
(quantity < 0) y el CHECK los rechazaba.
"""

from alembic import op

revision = "0111_price_check_cash_actions"
down_revision = "0110_drop_dup_portfolio_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # El CHECK de price ya nace estrecho en 0108: aqui no se toca.
    # ck_positions_quantity_non_negative se retira entera: el dominio admite
    # cortos (quantity < 0). market_prices.close >= 0 se mantiene.
    with op.batch_alter_table("positions", schema=None) as batch_op:
        batch_op.drop_constraint("ck_positions_quantity_non_negative", type_="check")


def downgrade() -> None:
    # Restaura solo lo que esta migracion retira; el CHECK de price vive en
    # 0108 (su downgrade lo retira entero). NOT VALID: en head el dominio
    # admite cortos, asi que validar al restaurar rechazaria filas legitimas
    # creadas en head (o exigiria borrarlas). NOT VALID guarda las escrituras
    # futuras sin tocar el dato existente.
    with op.batch_alter_table("positions", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_positions_quantity_non_negative",
            "quantity >= 0",
            postgresql_not_valid=True,
        )
