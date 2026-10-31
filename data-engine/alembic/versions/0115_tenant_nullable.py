"""tenant_id nullable donde los modelos lo declaran y la BD exige NOT NULL.

Revision ID: 0115_tenant_nullable
Revises: 0114_fk_ondelete_tenants
Create Date: 2026-10-31T02:12:00.000Z

MEDIDO (baseline del rachet, direccion bd NOT NULL -> modelo nullable):
tenant_id de alert_subscriptions, decision_journal_entries,
expectation_reviews, fundamental_assumptions, fundamental_drivers,
fundamental_forecasts, fundamental_model_versions, telegram_chat_bindings
y telegram_link_challenges. Los modelos (TenantOwnedMixin o columna
explicita) lo declaran nullable=True: filas legacy/anonimas sin tenant son
validas para la app, pero la BD migrada las rechazaba con IntegrityError.

DROP NOT NULL es permisivo: no invalida datos existentes ni exige
verificacion de prod (al reves que un SET NOT NULL). Guard por inspector:
idempotente. En sqlite, batch_alter_table reconstruye la tabla con la
columna nullable.

NO desplegar en produccion hasta que Nico lo decida.
"""

import sqlalchemy as sa

from alembic import op

revision = "0115_tenant_nullable"
down_revision = "0114_fk_ondelete_tenants"
branch_labels = None
depends_on = None

_TABLAS = [
    "alert_subscriptions",
    "decision_journal_entries",
    "expectation_reviews",
    "fundamental_assumptions",
    "fundamental_drivers",
    "fundamental_forecasts",
    "fundamental_model_versions",
    "telegram_chat_bindings",
    "telegram_link_challenges",
]


def _es_not_null(bind, tabla: str, columna: str) -> bool:
    return any(
        c["name"] == columna and not c["nullable"]
        for c in sa.inspect(bind).get_columns(tabla)
    )


def upgrade() -> None:
    bind = op.get_bind()
    for tabla in _TABLAS:
        if not _es_not_null(bind, tabla, "tenant_id"):
            continue
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.alter_column("tenant_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    for tabla in _TABLAS:
        if _es_not_null(bind, tabla, "tenant_id"):
            continue
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.alter_column("tenant_id", existing_type=sa.Integer(), nullable=False)
