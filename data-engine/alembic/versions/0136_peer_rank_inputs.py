"""Expand peer inputs without a table rewrite. Backfill is separate, bounded work.

Revision ID: 0136_peer_rank_inputs
Revises: 0135_management_alignment

Alternative to the unmerged STORED design, not a follow-up migration for it.
A nullable no-default column avoids the rewrite but still needs a short
ACCESS EXCLUSIVE metadata lock. Abort after 250ms rather than queue indefinitely.
Old application code remains compatible. New code reads NULLs via live fallback.
"""
from alembic import op
from app.valuation.peer_rank_projection import (
    ADD_COLUMN_SQL,
    ASSERT_WRITABLE_COLUMN_SQL,
    FUNCTION_SQL,
    TRIGGER_FUNCTION_SQL,
    TRIGGER_SQL,
)

revision = '0136_peer_rank_inputs'
down_revision = '0135_management_alignment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("SET LOCAL lock_timeout = '250ms'")
        op.execute(FUNCTION_SQL)
        op.execute(ADD_COLUMN_SQL)
        op.execute(ASSERT_WRITABLE_COLUMN_SQL)
        op.execute(TRIGGER_FUNCTION_SQL)
        op.execute(TRIGGER_SQL)


def downgrade() -> None:
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("SET LOCAL lock_timeout = '250ms'")
        op.execute('DROP TRIGGER IF EXISTS valuation_peer_rank_inputs_write ON valuation_outputs')
        op.execute('ALTER TABLE valuation_outputs DROP COLUMN IF EXISTS peer_rank_inputs')
        op.execute('DROP FUNCTION IF EXISTS valuation_peer_rank_inputs_write_v1()')
        op.execute('DROP FUNCTION IF EXISTS valuation_peer_rank_inputs_v1(json)')
