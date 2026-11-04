"""«Nuestro acierto»: lectura de cómo acertaron nuestros valores razonables.

Solo lee ``thesis_realized_returns`` (la rellena el job diario
``refresh_thesis_track_record``) y, para el estado pendiente, la fecha de la
primera versión con valor razonable. Acotado al tenant de la petición.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.company_resolver import resolve_company
from app.services.thesis_track_record_service import company_track_record, tenant_track_record

router = APIRouter()


class TrackRecordHorizonOut(BaseModel):
    samples: int
    hits: int
    hit_rate: float | None = None
    median_abs_error: float | None = None
    median_signed_error: float | None = None
    touched_rate: float | None = None


class TrackRecordBase(BaseModel):
    status: Literal["ready", "pending", "no_data"]
    first_maturity_date: str | None = None
    horizons: dict[str, TrackRecordHorizonOut]
    best_horizon: str | None = None
    best_horizon_reason: str
    min_samples_best_horizon: int
    versions_tracked: int
    last_computed_at: datetime | None = None


class CompanyTrackRecordOut(TrackRecordBase):
    ticker: str


class TickerTrackRecordOut(BaseModel):
    ticker: str
    horizons: dict[str, TrackRecordHorizonOut]
    best_horizon: str | None = None
    best_horizon_reason: str


class TenantTrackRecordOut(TrackRecordBase):
    tickers: list[TickerTrackRecordOut]


@router.get("/companies/{ticker}/track-record", response_model=CompanyTrackRecordOut)
def get_company_track_record(ticker: str, db: Session = Depends(get_db)) -> dict:
    """Acierto de nuestros valores razonables para una empresa (6 y 12 meses)."""
    company = resolve_company(db, ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company_track_record(db, company)


@router.get("/thesis-track-record", response_model=TenantTrackRecordOut)
def get_tenant_track_record(db: Session = Depends(get_db)) -> dict:
    """Acierto agregado del tenant y por ticker, con el mejor horizonte de cada uno."""
    return tenant_track_record(db)
