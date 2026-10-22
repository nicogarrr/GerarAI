"""management_promises: procedencia verificable de cada compromiso.

Aditiva, todo nullable, sin backfill: NULL significa «no registrado». La fecha
de alta en BD de un CallClaim no es la fecha de la llamada, por eso se anade
date_basis. Reversible en dev (DROP COLUMN); un downgrade prod con datos
registrados los perderia y va aparte, con backup restorable.
"""
import sqlalchemy as sa

from alembic import op

revision = "0078_promise_provenance"
down_revision = "0077_plan_monthly_currency"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("quote_literal", sa.Text()),
    ("quote_translation_es", sa.Text()),
    ("speaker", sa.String(160)),
    ("speaker_role", sa.String(120)),
    ("call_date", sa.Date()),
    ("source_url", sa.String(1000)),
    ("transcript_locator", sa.String(200)),
    ("due_date", sa.Date()),
    ("fulfillment_criteria", sa.Text()),
    ("status_reason", sa.Text()),
    ("date_basis", sa.String(20)),
]


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("management_promises", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("management_promises", name)
