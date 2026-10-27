"""Columna transaction_id en decision_journal_entries: diario enlazado a operaciones.

Aditiva y nullable. Una entrada del diario de decisiones puede apuntar a la
operacion real (``transactions``: compra/venta importada de IBKR o manual) que
la ejecuto. ``ON DELETE SET NULL``: borrar o reimportar una operacion nunca
borra la entrada del diario.

Se usa ``batch_alter_table`` para que SQLite (tests) pueda anadir y quitar la
clave foranea; en Postgres son ALTER TABLE normales.

Numeracion: 0083 la usa la rama del motor DCA, 0084 la biblioteca con ticker y
0085 los criterios de invalidacion de la tesis (todas en PR). Si esta se
mergea antes que alguna, ajusta ``down_revision`` al head que haya en main.

Sin backfill: las entradas existentes quedan sin operacion.
"""

import sqlalchemy as sa

from alembic import op

revision = "0086_journal_transaction_link"
down_revision = "0083_dca_signal_states"
branch_labels = None
depends_on = None

_TABLE = "decision_journal_entries"
_FK = "fk_decision_journal_entries_transaction_id"
_INDEX = "ix_decision_journal_entries_transaction_id"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("transaction_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(_FK, "transactions", ["transaction_id"], ["id"], ondelete="SET NULL")
        batch.create_index(_INDEX, ["transaction_id"])


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(_INDEX)
        batch.drop_constraint(_FK, type_="foreignkey")
        batch.drop_column("transaction_id")
