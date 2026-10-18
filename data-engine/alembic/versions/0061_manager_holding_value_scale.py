"""Escala usada al guardar el valor de un holding 13F (heuristica por filing)."""
import sqlalchemy as sa

from alembic import op

revision = "0061_manager_holding_value_scale"
down_revision = "0060_marco_version_rename"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("manager_holdings", sa.Column("value_scale", sa.String(24), nullable=True))


def downgrade() -> None:
    op.drop_column("manager_holdings", "value_scale")
