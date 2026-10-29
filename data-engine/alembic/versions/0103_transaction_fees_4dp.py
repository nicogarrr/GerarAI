"""Comisiones con 4 decimales: transactions.fees Numeric(20,2) -> Numeric(20,4).

IBKR cobra fracciones de céntimo (p. ej. 0,355 USD) y Numeric(20,2) las
redondeaba en silencio. Ensanchar la escala no pierde datos (los valores
existentes ya tienen 2 decimales). El downgrade vuelve a Numeric(20,2) y
REDONDEA a 2 decimales las comisiones que tengan más.
"""
import sqlalchemy as sa

from alembic import op

revision = "0103_transaction_fees_4dp"
down_revision = "0102_position_statement_as_of"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column(
            "fees",
            existing_type=sa.Numeric(20, 2),
            type_=sa.Numeric(20, 4),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column(
            "fees",
            existing_type=sa.Numeric(20, 4),
            type_=sa.Numeric(20, 2),
            existing_nullable=False,
        )
