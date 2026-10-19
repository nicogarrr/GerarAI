"""Columna rule_10b5_1 en insider_transactions (ventas planificadas Form 4).

Aditiva: filas existentes quedan en false hasta que el backfill acotado
re-lea su XML (insider_monitor.backfill_rule_10b5_1).
"""
import sqlalchemy as sa

from alembic import op

revision = "0067_insider_rule_10b5_1"
down_revision = "0066_benchmark_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "insider_transactions",
        sa.Column(
            "rule_10b5_1",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("insider_transactions", "rule_10b5_1")
