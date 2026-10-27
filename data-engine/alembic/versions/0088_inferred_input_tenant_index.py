"""Index private inferred inputs without rewriting ownership or losing legacy rows."""
import sqlalchemy as sa

from alembic import op

revision = "0088_inferred_input_tenant_index"
down_revision = "0087_market_price_quote_unit"
branch_labels = None
depends_on = None

INDEX = "ix_inferred_inputs_tenant_company_key"


def upgrade() -> None:
    # tenant_id already exists and retains its exact historical creator value.
    # NULL owners remain quarantined in place. No guessed backfill or copying.
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("inferred_inputs")}
    if INDEX not in indexes:
        op.create_index(INDEX, "inferred_inputs", ["tenant_id", "company_id", "input_key"])


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("inferred_inputs")}
    if INDEX in indexes:
        op.drop_index(INDEX, table_name="inferred_inputs")
