"""Tenant-wide directional DCA notifications; old symbol overrides are retained."""
from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.entities import TenantOwnedMixin, TimestampMixin


class DcaAlertSettings(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "dca_alert_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_dca_alert_settings_tenant"),
        CheckConstraint("up_min_level BETWEEN 0 AND 4", name="ck_dca_up_level"),
        CheckConstraint("down_max_level BETWEEN 0 AND 4", name="ck_dca_down_level"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # 0 disables the direction. No rows are created until the user saves.
    up_min_level: Mapped[int] = mapped_column(Integer)
    down_max_level: Mapped[int] = mapped_column(Integer)
