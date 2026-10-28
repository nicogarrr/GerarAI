"""One reporting-only IBKR source account per tenant."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TenantOwnedMixin, TimestampMixin


class IBKRConnection(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "ibkr_connections"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_ibkr_connection_tenant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_id: Mapped[str] = mapped_column(String(32))
    account_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    complete_query: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="connected")
    message: Mapped[str] = mapped_column(String(500), default="Conexión verificada. Pendiente de sincronizar.")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    statement_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class IBKRSyncReceipt(TenantOwnedMixin, Base):
    """Append-only attempt history. No XML, tokens or upstream errors."""
    __tablename__ = "ibkr_sync_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    result: Mapped[str] = mapped_column(String(24), default="running")
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(40))
