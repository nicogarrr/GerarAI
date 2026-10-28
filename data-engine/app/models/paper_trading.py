"""Immutable LLM proposals and forward-only simulated executions."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TenantOwnedMixin, TimestampMixin


class PaperTrade(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "paper_trades"
    __table_args__ = (UniqueConstraint("tenant_id", "proposal_key", name="uq_paper_proposal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_key: Mapped[str] = mapped_column(String(120))
    ticker: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(8))
    horizon: Mapped[str] = mapped_column(String(16))
    thesis: Mapped[str] = mapped_column(Text)
    conviction: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    proposed_entry: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    stop: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    target: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    author: Mapped[str] = mapped_column(String(8), default="LLM")
    inference_label: Mapped[str] = mapped_column(String(16), default="inferencia")
    inference_basis: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    # Immutable proposal input, separate from the observed quote currency.
    # Legacy rows remain explicitly unknown, never inferred from a mark.
    proposal_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    proposal_currency_known: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    mark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(20))
    price_source: Mapped[str | None] = mapped_column(String(80))
    # Supuesto de coste persistido al ejecutar (ver paper_cost_service).
    # NULL = trade anterior al modelo de costes: su neto es N/D, nunca se rellena.
    entry_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    exit_fee: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    cost_assumption_version: Mapped[str | None] = mapped_column(String(80))
    # Dividendos devengados (DividendRecord con fuente) y ajustes por splits.
    # NULL = no computado (trade legado o empresa fuera del tenant).
    dividends_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    dividends_count: Mapped[int | None] = mapped_column()
    dividends_uncertain: Mapped[int | None] = mapped_column()
    dividends_wrong_currency: Mapped[int | None] = mapped_column()
    dividends_source: Mapped[str | None] = mapped_column(String(160))
    split_adjustments: Mapped[int | None] = mapped_column()
    applied_split_ids: Mapped[str | None] = mapped_column(String(500))
    last_corporate_action: Mapped[str | None] = mapped_column(String(160))
    corporate_action_warning: Mapped[str | None] = mapped_column(String(60))
