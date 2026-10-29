"""Web Push (PWA): dispositivos y preferencias por tipo de evento.

Solo crea tablas nuevas, vacias: nadie recibe push hasta que el usuario activa
el permiso del navegador y un tipo de evento. Downgrade las elimina; no toca
alertas ni suscripciones de Telegram. Idempotente si create_all ya las creo.
"""
import sqlalchemy as sa

from alembic import op

revision = "0101_web_push"
down_revision = "0100_ibkr_raw_row_snapshot_keys"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()
    if "push_subscriptions" not in existing:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("user_id", sa.String(160), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("endpoint_hash", sa.String(64), nullable=False),
            sa.Column("p256dh", sa.String(200), nullable=False),
            sa.Column("auth_secret", sa.String(100), nullable=False),
            sa.Column("user_agent", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "endpoint_hash", name="uq_push_subscription_endpoint"),
        )
        op.create_index("ix_push_subscriptions_tenant_id", "push_subscriptions", ["tenant_id"])
    if "push_preferences" not in existing:
        op.create_table(
            "push_preferences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("user_id", sa.String(160), nullable=False),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "user_id", "event_type", name="uq_push_preference_type"),
        )
        op.create_index("ix_push_preferences_tenant_id", "push_preferences", ["tenant_id"])


def downgrade() -> None:
    existing = _tables()
    for table in ("push_preferences", "push_subscriptions"):
        if table in existing:
            op.drop_table(table)
