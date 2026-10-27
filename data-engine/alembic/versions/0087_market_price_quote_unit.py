"""Preserve the provider's exact quote unit; no guessed legacy backfill."""
import sqlalchemy as sa

from alembic import op

revision = "0087_market_price_quote_unit"
down_revision = "0086_journal_transaction_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # init_db/create_all may have created the nullable field before Alembic.
    columns = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("market_prices")}
    existing = columns.get("quote_currency")
    if existing is not None:
        if not existing["nullable"] or not isinstance(existing["type"], sa.String) or existing["type"].length != 12:
            raise RuntimeError("market_prices.quote_currency schema mismatch")
        return
    op.add_column("market_prices", sa.Column("quote_currency", sa.String(12), nullable=True))


def downgrade() -> None:
    op.drop_column("market_prices", "quote_currency")
