"""Telemetría propia de /api/chat (€0, sin Langfuse).

Pregunta, ruta (LLM/determinista), latencia y error por tenant, para medir
latencias reales del chat (p. ej. el reintento CJK del llm_output_guard)
sin depender de servicios externos.
"""
import sqlalchemy as sa

from alembic import op

revision = "0063_chat_telemetry"
down_revision = "0062_financial_fact_fk_ondelete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("route", sa.String(60), nullable=False),
        sa.Column("used_llm", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model", sa.String(160), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_telemetry_events_tenant_id", "chat_telemetry_events", ["tenant_id"])
    op.create_index("ix_chat_telemetry_events_route", "chat_telemetry_events", ["route"])


def downgrade() -> None:
    op.drop_index("ix_chat_telemetry_events_route", table_name="chat_telemetry_events")
    op.drop_index("ix_chat_telemetry_events_tenant_id", table_name="chat_telemetry_events")
    op.drop_table("chat_telemetry_events")
