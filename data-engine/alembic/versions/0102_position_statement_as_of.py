"""positions.statement_as_of: fecha del extracto que fijo cantidad y coste.

Solo anade una columna nullable sin default (sin reescritura de tabla, sin
backfill: NULL significa "usa as_of", el comportamiento previo). Idempotente si
create_all ya la creo. Downgrade la elimina.
"""
import sqlalchemy as sa

from alembic import op

revision = "0102_position_statement_as_of"
down_revision = "0101_web_push"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return "statement_as_of" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("positions")}


def upgrade() -> None:
    if not _has_column():
        op.add_column("positions", sa.Column("statement_as_of", sa.Date(), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("positions", "statement_as_of")
