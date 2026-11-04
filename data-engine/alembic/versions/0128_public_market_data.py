"""Add empty public-provider tables. No copy/update/delete of tenant rows."""
import sqlalchemy as sa

from alembic import op

revision = '0128_public_market_data'
down_revision = '0127_declared_input_values'
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'public_source_documents' not in existing:
        op.create_table('public_source_documents',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('listing_key', sa.String(160), nullable=False),
            sa.Column('provider', sa.String(40), nullable=False),
            sa.Column('source_url', sa.String(2000), nullable=False),
            sa.Column('checksum', sa.String(64), nullable=False),
            sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('official', sa.Boolean(), nullable=False), *_timestamps(),
            sa.UniqueConstraint('company_id', 'listing_key', 'provider', 'source_url', 'checksum', name='uq_public_source_identity'))
        op.create_index('ix_public_source_documents_company_id', 'public_source_documents', ['company_id'])
    if 'public_financial_facts' not in existing:
        op.create_table('public_financial_facts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('public_source_documents.id'), nullable=False),
            sa.Column('metric', sa.String(120), nullable=False),
            sa.Column('value', sa.Numeric(30, 8), nullable=False),
            sa.Column('unit', sa.String(40), nullable=False),
            sa.Column('period_end', sa.Date(), nullable=False),
            sa.Column('period_start', sa.Date(), nullable=True),
            sa.Column('fiscal_quarter', sa.String(10), nullable=False),
            sa.Column('filed', sa.Date(), nullable=True),
            sa.Column('concept_namespace', sa.String(100), nullable=True),
            sa.Column('concept_name', sa.String(200), nullable=False),
            sa.Column('accession', sa.String(100), nullable=True),
            sa.Column('confidence', sa.Numeric(5, 4), nullable=False),
            sa.Column('derived', sa.Boolean(), nullable=False),
            sa.Column('derived_from_refs', sa.JSON(), nullable=False), *_timestamps(),
            sa.UniqueConstraint('source_document_id', 'metric', 'period_end', 'unit', 'concept_name', name='uq_public_fact_source_period'))
        op.create_index('ix_public_financial_facts_source_document_id', 'public_financial_facts', ['source_document_id'])
        op.create_index('ix_public_financial_facts_metric', 'public_financial_facts', ['metric'])
    if 'public_financial_statements' not in existing:
        op.create_table('public_financial_statements',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('public_source_documents.id'), nullable=False),
            sa.Column('statement_type', sa.String(40), nullable=False),
            sa.Column('period_end', sa.Date(), nullable=False),
            sa.Column('unit', sa.String(40), nullable=False),
            sa.Column('metrics', sa.JSON(), nullable=False), *_timestamps(),
            sa.UniqueConstraint('source_document_id', 'statement_type', 'period_end', 'unit', name='uq_public_statement_source_period'))
        op.create_index('ix_public_financial_statements_source_document_id', 'public_financial_statements', ['source_document_id'])
    if 'public_analyst_targets' not in existing:
        op.create_table('public_analyst_targets',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('source_document_id', sa.Integer(), sa.ForeignKey('public_source_documents.id'), nullable=False),
            sa.Column('firm', sa.String(200), nullable=False),
            sa.Column('published_on', sa.Date(), nullable=False),
            sa.Column('value', sa.Numeric(30, 8), nullable=False),
            sa.Column('unit', sa.String(40), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False), *_timestamps(),
            sa.UniqueConstraint('source_document_id', 'firm', 'published_on', name='uq_public_analyst_source_firm_date'))
        op.create_index('ix_public_analyst_targets_source_document_id', 'public_analyst_targets', ['source_document_id'])


def downgrade():
    # Rollback removes only these new tables, never a tenant-owned table.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ('public_analyst_targets', 'public_financial_statements', 'public_financial_facts', 'public_source_documents'):
        if name in existing:
            op.drop_table(name)
