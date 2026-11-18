"""Cover tenant/company counts used by research snapshots.

Revision ID: 0138_facts_tenant_company_idx
Revises: 0137_form144_notices

Measured locally on 20M synthetic rows, not a production A/B. Production
catalog evidence showed no equivalent general tenant/company index. See
 docs/performance/financial-facts-tenant-company-index.md for limits.
"""
import sqlalchemy as sa

from alembic import op

revision = "0138_facts_tenant_company_idx"
down_revision = "0137_form144_notices"
branch_labels = None
depends_on = None

INDEX = "ix_facts_tenant_company_count"
TABLE = "financial_facts"


def _schema(bind) -> str:
    # Bind DDL to the namespace of the table resolved by regclass, not to
    # the first same-named index found along search_path.
    return bind.execute(sa.text(
        "SELECT n.nspname FROM pg_class t "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE t.oid=cast(:table_name AS regclass)"
    ), {"table_name": TABLE}).scalar_one()


def _invalid(bind) -> bool:
    # Resolve the table through the migration connection's search_path, never
    # drop a same-named index belonging to another table/schema.
    return bool(bind.execute(sa.text(
        "SELECT 1 FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid "
        "WHERE i.indrelid=cast(:table_name AS regclass) "
        "AND idx.relname=:index_name AND NOT i.indisvalid"
    ), {"table_name": TABLE, "index_name": INDEX}).first())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL disallows CONCURRENTLY inside a transaction. Alembic's
        # block commits prior work, then runs each DDL in autocommit mode.
        with op.get_context().autocommit_block():
            schema = _schema(bind)
            if _invalid(bind):
                op.drop_index(INDEX, table_name=TABLE, schema=schema,
                              postgresql_concurrently=True, if_exists=True)
            op.create_index(INDEX, TABLE, ["tenant_id", "company_id"], schema=schema,
                            postgresql_concurrently=True, if_not_exists=True)
        return
    existing = {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}
    if INDEX not in existing:
        op.create_index(INDEX, TABLE, ["tenant_id", "company_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(INDEX, table_name=TABLE, schema=_schema(bind),
                          postgresql_concurrently=True, if_exists=True)
        return
    op.drop_index(INDEX, table_name=TABLE, if_exists=True)
