"""Serie diaria de un benchmark (SPY) ingerida de Yahoo, fuera del master.

Un Company SPY global se colaria en el embudo, los movers y los jobs de
todas las cuentas; por eso el benchmark vive en su propia tabla, con la
misma regla de siempre: cada valor lleva su fuente y su fecha.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class BenchmarkPrice(Base, TimestampMixin):
    __tablename__ = "benchmark_prices"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_benchmark_price_symbol_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="yfinance")
