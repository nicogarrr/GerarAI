"""Flujos de dinero por tema. GET nunca ingesta ni llama a un LLM.

Fuentes: financial_facts SEC/ESEF ya ingeridos (capex reportado) y la API
pública de USAspending (defensa), cacheada 1 h como las velas de /api/market.
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ui_errors import ui_error
from app.services.money_flows import FLOW_THEMES, build_theme_payload, theme_summaries

router = APIRouter()


class FlowSourceOut(BaseModel):
    kind: Literal["reportado", "estimacion_terceros"]
    label: str
    url: str | None = None
    note: str | None = None


class FlowSpenderOut(BaseModel):
    key: str
    label: str
    ticker: str | None = None
    amount: float | None = None
    unit: str = "USD"
    period_label: str | None = None
    source: FlowSourceOut | None = None
    reason: str | None = None
    note: str | None = None
    extra_amount: float | None = None
    extra_label: str | None = None
    extra_source: FlowSourceOut | None = None


class FlowDestinationOut(BaseModel):
    label: str
    amount: float | None = None
    unit: str = "USD"
    source: FlowSourceOut


class FlowSupplierOut(BaseModel):
    ticker: str | None = None
    name: str
    amount: float | None = None
    unit: str = "USD"
    reason: str
    note: str | None = None
    source: FlowSourceOut | None = None


class FlowTotalOut(BaseModel):
    amount: float
    unit: str = "USD"
    note: str


class FlowThemeOut(BaseModel):
    id: str
    name: str
    tagline: str
    generated_at: datetime
    period_label: str | None = None
    spenders: list[FlowSpenderOut]
    spenders_total: FlowTotalOut | None = None
    destinations: list[FlowDestinationOut]
    suppliers: list[FlowSupplierOut]
    method: str
    limitation: str
    notes: list[str] = []
    destinations_note: str | None = None
    suppliers_note: str | None = None


class FlowThemeSummaryOut(BaseModel):
    id: str
    name: str
    tagline: str


@router.get("/themes", response_model=list[FlowThemeSummaryOut], summary="Temas con flujo de dinero")
def list_flow_themes() -> list[FlowThemeSummaryOut]:
    return [FlowThemeSummaryOut(**item) for item in theme_summaries()]


@router.get("/themes/{theme_id}", response_model=FlowThemeOut, summary="Flujo de dinero de un tema")
def get_flow_theme(theme_id: str, db: Session = Depends(get_db)) -> FlowThemeOut:
    theme = FLOW_THEMES.get(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail=ui_error(404, "flow_topic_not_configured").detail)
    tenant = db.info.get("tenant_id")
    payload = build_theme_payload(db, theme, tenant if isinstance(tenant, int) else None)
    return FlowThemeOut(**payload)
