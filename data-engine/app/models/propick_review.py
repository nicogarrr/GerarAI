"""LLM review verdicts on ProPicks shortlists, logged for calibration."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TenantOwnedMixin, TimestampMixin


class PropickReview(TenantOwnedMixin, Base, TimestampMixin):
    __tablename__ = "propick_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    decision: Mapped[str] = mapped_column(String(12))  # keep | veto
    confidence: Mapped[float] = mapped_column(Float)  # 0..1, the LLM's own probability
    base_score: Mapped[float] = mapped_column(Float)  # deterministic score at review time
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    verdict: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
