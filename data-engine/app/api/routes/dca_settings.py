from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.core.auth import MSG_IDENTITY_REQUIRED
from app.core.database import get_db
from app.services.dca_alert_settings_service import save_policy, settings_view

router = APIRouter()


class DcaSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    up_min_level: int = Field(ge=0, le=4, strict=True)
    down_max_level: int = Field(ge=0, le=4, strict=True)


class DcaSettingsOut(DcaSettingsUpdate):
    configured: bool
    legacy_override_count: int
    legacy_min_level: int
    alerts_enabled: bool
    trims_enabled: bool


def _require_identity(db: Session) -> None:
    if db.info.get("tenant_id") is None:
        raise HTTPException(status_code=401, detail=MSG_IDENTITY_REQUIRED)


@router.get("", response_model=DcaSettingsOut)
def read_settings(db: Session = Depends(get_db)) -> dict:
    _require_identity(db)
    return settings_view(db)


@router.put("", response_model=DcaSettingsOut)
def update_settings(payload: DcaSettingsUpdate, db: Session = Depends(get_db)) -> dict:
    _require_identity(db)
    return save_policy(db, payload.up_min_level, payload.down_max_level)
