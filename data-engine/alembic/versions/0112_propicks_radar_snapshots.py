"""Public price-only radar snapshots and resumable daily cursor."""
import sqlalchemy as sa

from alembic import op

revision = '0112_propicks_radar_snapshots'
down_revision = '0111_price_check_cash_actions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('propicks_radar_snapshots',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
                    sa.Column('scan_date', sa.Date(), nullable=False),
                    sa.Column('formula_version', sa.String(80), nullable=False),
                    sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
                    sa.Column('status', sa.String(40), nullable=False),
                    sa.Column('payload', sa.JSON(), nullable=False),
                    sa.UniqueConstraint('company_id', 'scan_date', 'formula_version', name='uq_radar_company_scan_formula'))
    op.create_index('ix_propicks_radar_snapshots_company_id', 'propicks_radar_snapshots', ['company_id'])
    op.create_table('propicks_radar_cursors',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('scan_date', sa.Date(), nullable=False, unique=True),
                    sa.Column('after_company_id', sa.Integer(), nullable=False),
                    sa.Column('saved_count', sa.Integer(), nullable=False))


def downgrade():
    op.drop_table('propicks_radar_cursors')
    op.drop_index('ix_propicks_radar_snapshots_company_id', table_name='propicks_radar_snapshots')
    op.drop_table('propicks_radar_snapshots')
