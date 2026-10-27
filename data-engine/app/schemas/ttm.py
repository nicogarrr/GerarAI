"""Esquemas de la vista TTM (últimos 4 trimestres)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class TtmQuarterOut(BaseModel):
    period_end: date
    value: Decimal
    reported: bool
    # "10-Q" presentado, "YTD" (acumulado restado) o "FY-9M" (Q4 derivado).
    origin: str


class TtmMetricOut(BaseModel):
    metric: str
    value: Decimal | None
    unit: str | None
    basis: Literal["TTM", "FY", "Q", "SIN_DATOS"]
    label: str
    provenance: Literal["OFICIAL", "INFERIDO", "SIN_DATOS"]
    period_end: date | None
    note: str | None = None
    fact_ids: list[int] = Field(default_factory=list)
    quarters: list[TtmQuarterOut] = Field(default_factory=list)


class CompanyTtmOut(BaseModel):
    ticker: str
    as_of: date | None
    formula: str
    metrics: list[TtmMetricOut]
