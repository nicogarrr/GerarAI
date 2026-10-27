"""Keep immutable requested paper currency apart from the observed currency.

Legacy requests cannot be reconstructed from a mark: known stays false.
Downgrade removes only these new metadata columns, retaining every trade.
"""
import sqlalchemy as sa

from alembic import op

revision = "0090_paper_proposal_currency"
down_revision = "0089_ibkr_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("paper_trades")}
    if "proposal_currency" not in columns:
        op.add_column("paper_trades", sa.Column("proposal_currency", sa.String(8), nullable=True))
    elif not columns["proposal_currency"]["nullable"] or not isinstance(columns["proposal_currency"]["type"], sa.String) or columns["proposal_currency"]["type"].length != 8:
        raise RuntimeError("paper proposal currency schema mismatch")
    if "proposal_currency_known" not in columns:
        op.add_column("paper_trades", sa.Column("proposal_currency_known", sa.Boolean(), nullable=False, server_default=sa.false()))
    elif columns["proposal_currency_known"]["nullable"] or columns["proposal_currency_known"]["type"]._type_affinity != sa.Boolean:
        raise RuntimeError("paper proposal currency known schema mismatch")


def downgrade() -> None:
    with op.batch_alter_table("paper_trades") as batch:
        batch.drop_column("proposal_currency_known")
        batch.drop_column("proposal_currency")
