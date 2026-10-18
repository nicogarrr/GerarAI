"""Frozen monthly ProPicks snapshots (point-in-time, immutable)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TenantOwnedMixin, TimestampMixin


class PropickSnapshot(TenantOwnedMixin, Base, TimestampMixin):
    """One row per tenant and month. Never updated after creation: it is the
    point-in-time record that makes a future backtest free of look-ahead."""

    __tablename__ = "propick_snapshots"
    __table_args__ = (UniqueConstraint("tenant_id", "month", name="uq_propick_snapshot_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    funnel_version: Mapped[str] = mapped_column(String(80))
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
