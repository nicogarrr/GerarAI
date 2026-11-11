"""Persist per-watch-item automatic analysis choice, enabled for existing rows.

Uses migration_added_columns from 0132 so ORM-created columns survive downgrade.
"""
import sqlalchemy as sa

from alembic import op

revision = '0133_watch_auto_analysis'
down_revision = '0132_dca_state_live_price'
branch_labels = None
depends_on = None

_TABLE = 'watch_items'
_COLUMN = 'auto_analysis_enabled'
_LOG = 'migration_added_columns'


def _offline():
    from sqlalchemy.engine.mock import MockConnection
    return isinstance(op.get_bind(), MockConnection)


def upgrade():
    bind = op.get_bind()
    if not _offline() and _COLUMN in {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}:
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Boolean(), server_default=sa.true(), nullable=False))
    op.execute(sa.text(
        f"INSERT INTO {_LOG} (revision, table_name, column_name) "
        f"VALUES ('{revision}', '{_TABLE}', '{_COLUMN}')"
    ))


def downgrade():
    bind = op.get_bind()
    if not _offline():
        if not sa.inspect(bind).has_table(_LOG):
            return
        owned = bind.execute(sa.text(
            f'SELECT column_name FROM {_LOG} WHERE revision=:r AND table_name=:t'
        ), {'r': revision, 't': _TABLE}).scalars().all()
        if _COLUMN not in owned:
            return
        if _COLUMN in {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}:
            op.drop_column(_TABLE, _COLUMN)
    else:
        op.drop_column(_TABLE, _COLUMN)
    op.execute(sa.text(f"DELETE FROM {_LOG} WHERE revision='{revision}' AND table_name='{_TABLE}'"))
