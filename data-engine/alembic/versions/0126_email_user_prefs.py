"""Correo por usuario: destino verificado y opt-in por tipo de evento.

Solo crea tablas nuevas, vacias: nadie recibe correo por usuario hasta que el
frontend firma su direccion (user_email_bindings) y el usuario activa un tipo
(email_preferences). Downgrade las elimina; no toca el destino global
ALERT_EMAIL_TO ni las suscripciones de Telegram/push. Idempotente si
create_all ya las creo.
"""
import sqlalchemy as sa

from alembic import op

revision = "0126_email_user_prefs"
down_revision = "0125_news_lane_idx"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()
    if "user_email_bindings" not in existing:
        op.create_table(
            "user_email_bindings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("user_id", sa.String(160), nullable=False),
            sa.Column("address", sa.String(320), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "user_id", name="uq_user_email_binding_owner"),
        )
        op.create_index("ix_user_email_bindings_tenant_id", "user_email_bindings", ["tenant_id"])
    if "email_preferences" not in existing:
        op.create_table(
            "email_preferences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("user_id", sa.String(160), nullable=False),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "user_id", "event_type", name="uq_email_preference_type"),
        )
        op.create_index("ix_email_preferences_tenant_id", "email_preferences", ["tenant_id"])


def downgrade() -> None:
    existing = _tables()
    for table in ("email_preferences", "user_email_bindings"):
        if table in existing:
            op.drop_table(table)
