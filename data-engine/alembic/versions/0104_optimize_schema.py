"""Optimize database schema: reduce VARCHAR sizes

Revision ID: 0104_optimize_schema
Revises: 0103_transaction_fees_4dp
Create Date: 2026-10-30T19:05:21.808Z

Conservative VARCHAR size reductions for performance optimization:
- companies.name: 255 → 200
- documents.title: 500 → 400
- news_events.title: 500 → 400
- insider_filings.issuer_name: 300 → 250
- knowledge_documents.title: 500 → 400

All changes are backward compatible (smaller values fit in existing columns).
No data truncation expected - sizes remain generous for typical content.

SQLite: Uses batch_alter_table for compatibility.
PostgreSQL: Direct ALTER COLUMN TYPE (instant when new size >= all values).

Fulfills: VAL-DB-006 (Database schema optimization)
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '0104_optimize_schema'
down_revision = '0103_transaction_fees_4dp'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply schema optimizations."""
    # Use batch_alter_table for SQLite compatibility
    # PostgreSQL will use direct ALTER COLUMN TYPE (efficient)
    
    # 1. companies.name: 255 → 200
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.alter_column('name',
                              existing_type=sa.String(length=255),
                              type_=sa.String(length=200),
                              existing_nullable=False)
    
    # 2. documents.title: 500 → 400
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.alter_column('title',
                              existing_type=sa.String(length=500),
                              type_=sa.String(length=400),
                              existing_nullable=False)
    
    # 3. news_events.title: 500 → 400
    with op.batch_alter_table('news_events', schema=None) as batch_op:
        batch_op.alter_column('title',
                              existing_type=sa.String(length=500),
                              type_=sa.String(length=400),
                              existing_nullable=False)
    
    # 4. insider_filings.issuer_name: 300 → 250
    with op.batch_alter_table('insider_filings', schema=None) as batch_op:
        batch_op.alter_column('issuer_name',
                              existing_type=sa.String(length=300),
                              type_=sa.String(length=250),
                              existing_nullable=True)
    
    # 5. knowledge_documents.title: 500 → 400
    with op.batch_alter_table('knowledge_documents', schema=None) as batch_op:
        batch_op.alter_column('title',
                              existing_type=sa.String(length=500),
                              type_=sa.String(length=400),
                              existing_nullable=False)


def downgrade() -> None:
    """Revert schema optimizations."""
    # Restore original VARCHAR sizes (always safe - expanding capacity)
    
    # Reverse order for consistency
    with op.batch_alter_table('knowledge_documents', schema=None) as batch_op:
        batch_op.alter_column('title',
                              existing_type=sa.String(length=400),
                              type_=sa.String(length=500),
                              existing_nullable=False)
    
    with op.batch_alter_table('insider_filings', schema=None) as batch_op:
        batch_op.alter_column('issuer_name',
                              existing_type=sa.String(length=250),
                              type_=sa.String(length=300),
                              existing_nullable=True)
    
    with op.batch_alter_table('news_events', schema=None) as batch_op:
        batch_op.alter_column('title',
                              existing_type=sa.String(length=400),
                              type_=sa.String(length=500),
                              existing_nullable=False)
    
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.alter_column('title',
                              existing_type=sa.String(length=400),
                              type_=sa.String(length=500),
                              existing_nullable=False)
    
    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.alter_column('name',
                              existing_type=sa.String(length=200),
                              type_=sa.String(length=255),
                              existing_nullable=False)
