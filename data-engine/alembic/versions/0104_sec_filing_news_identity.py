"""Unique tenant/accession identity for SEC filing news (nullable for other news)."""

import sqlalchemy as sa

from alembic import op

revision = "0104_sec_filing_news_identity"
down_revision = "0103_transaction_fees_4dp"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("news_events") as batch:
        batch.add_column(sa.Column("sec_filing_identity", sa.String(100), nullable=True))
        batch.create_unique_constraint("uq_news_sec_filing_identity", ["sec_filing_identity"])


def downgrade():
    # Mismo guard que 0107: en SQLite un rebuild batch intermedio (0105 altera
    # news_events.title) pierde el nombre de la constraint; en PostgreSQL
    # persiste y la retirada es exacta.
    inspector = sa.inspect(op.get_bind())
    with op.batch_alter_table("news_events") as batch:
        nombres = {c["name"] for c in inspector.get_unique_constraints("news_events") if c.get("name")}
        if "uq_news_sec_filing_identity" in nombres:
            batch.drop_constraint("uq_news_sec_filing_identity", type_="unique")
        batch.drop_column("sec_filing_identity")
