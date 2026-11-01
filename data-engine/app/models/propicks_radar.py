"""Shared public-price scan snapshots. Never store private tenant quality here."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProPicksRadarSnapshot(Base):
    __tablename__ = 'propicks_radar_snapshots'
    __table_args__ = (UniqueConstraint('company_id', 'scan_date', 'formula_version',
                                      name='uq_radar_company_scan_formula'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), index=True)
    scan_date: Mapped[date] = mapped_column(Date)
    formula_version: Mapped[str] = mapped_column(String(80))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)


class ProPicksRadarCursor(Base):
    """LEGADA, sin uso desde nico-v2: el cursor se deriva de los snapshots.

    Sin formula_version, un cambio de formula a mitad de dia heredaba el
    progreso de la formula anterior. La clase se conserva para no invalidar
    las migraciones existentes; ningun codigo la lee ni la escribe.
    """
    __tablename__ = 'propicks_radar_cursors'
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_date: Mapped[date] = mapped_column(Date, unique=True)
    after_company_id: Mapped[int] = mapped_column(Integer, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, default=0)
