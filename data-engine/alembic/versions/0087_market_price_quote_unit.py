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
        # An adopted column was not created by this migration. Leave a
        # durable marker so downgrade cannot drop someone else's data.
        if not sa.inspect(op.get_bind()).has_table("market_price_unit_adoptions"):
            op.create_table("market_price_unit_adoptions", sa.Column("revision", sa.String(64), primary_key=True))
        bind = op.get_bind()
        if not bind.execute(sa.text("SELECT revision FROM market_price_unit_adoptions WHERE revision=:r"), {"r": revision}).first():
            bind.execute(sa.text("INSERT INTO market_price_unit_adoptions(revision) VALUES (:r)"), {"r": revision})
        return
    op.add_column("market_prices", sa.Column("quote_currency", sa.String(12), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("market_price_unit_adoptions"):
        adopted = bind.execute(sa.text("SELECT revision FROM market_price_unit_adoptions WHERE revision=:r"), {"r": revision}).first()
        if adopted:
            bind.execute(sa.text("DELETE FROM market_price_unit_adoptions WHERE revision=:r"), {"r": revision})
            if not bind.execute(sa.text("SELECT revision FROM market_price_unit_adoptions")).first():
                op.drop_table("market_price_unit_adoptions")
            return
    op.drop_column("market_prices", "quote_currency")
