"""Ancla cada propuesta del paper book a la tesis vigente del tenant.

NULL en los trades existentes: no se infiere a posteriori qué tesis vio el
modelo. Downgrade retira solo la columna, su índice y su FK; no toca trades
ni tesis. Idempotente: si un create_all ya creó la columna, no se duplica.
"""
import sqlalchemy as sa

from alembic import op

revision = "0099_paper_trade_thesis_version"
down_revision = "0098_dca_direction_settings"
branch_labels = None
depends_on = None

_TABLE = "paper_trades"
_COLUMN = "thesis_version_id"
_FK = "fk_paper_trades_thesis_version_id"
_INDEX = "ix_paper_trades_thesis_version_id"


def _has_column(inspector) -> bool:
    return _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_column(sa.inspect(op.get_bind())):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.Integer(), nullable=True))
            batch.create_foreign_key(_FK, "thesis_versions", [_COLUMN], ["id"], ondelete="SET NULL")
    if not any(ix["name"] == _INDEX for ix in sa.inspect(op.get_bind()).get_indexes(_TABLE)):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_column(inspector):
        return
    if any(ix["name"] == _INDEX for ix in inspector.get_indexes(_TABLE)):
        op.drop_index(_INDEX, table_name=_TABLE)
    foreign_keys = [
        fk["name"] for fk in inspector.get_foreign_keys(_TABLE)
        if fk.get("name") and _COLUMN in (fk.get("constrained_columns") or [])
    ]
    with op.batch_alter_table(_TABLE) as batch:
        for name in foreign_keys:
            batch.drop_constraint(name, type_="foreignkey")
        batch.drop_column(_COLUMN)
