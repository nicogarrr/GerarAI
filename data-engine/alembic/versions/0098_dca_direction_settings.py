"""Directional DCA policy, with effective defaults 3X up / 1X down.

No backfill and no edits to legacy ticker overrides. Downgrade returns to the
legacy behavior and drops only the new directional policy table.
"""
import sqlalchemy as sa
from alembic import op

revision = "0098_dca_direction_settings"
down_revision = "0097_ibkr_sync_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import DcaAlertSettings
    table = DcaAlertSettings.__table__
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(table.name):
        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        if set(columns) != set(table.columns.keys()):
            raise RuntimeError("dca_alert_settings schema mismatch")
        for col in table.columns:
            actual = columns[col.name]
            if actual["nullable"] != col.nullable or actual["type"]._type_affinity != col.type._type_affinity:
                raise RuntimeError("dca_alert_settings column mismatch")
        if not any(c["column_names"] == ["tenant_id"] for c in inspector.get_unique_constraints(table.name)):
            raise RuntimeError("dca_alert_settings uniqueness missing")
        if not any(fk["constrained_columns"] == ["tenant_id"] and fk["referred_table"] == "tenants" for fk in inspector.get_foreign_keys(table.name)):
            raise RuntimeError("dca_alert_settings tenant foreign key missing")
        expected_checks = {"ck_dca_up_level", "ck_dca_down_level"}
        if not expected_checks.issubset({c["name"] for c in inspector.get_check_constraints(table.name)}):
            raise RuntimeError("dca_alert_settings validation missing")
        return
    table.create(bind)


def downgrade() -> None:
    op.drop_table("dca_alert_settings")
