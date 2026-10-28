"""Tenant-wide directional policy, with effective defaults 3X up / 1X down."""
from types import SimpleNamespace
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.tenancy import tenant_filters
from app.models import DcaAlertOverride, DcaAlertSettings


def stored_policy(db: Session) -> DcaAlertSettings | None:
    # Never let an unscoped dev session pick another user's global policy.
    if db.info.get("tenant_id") is None:
        return None
    return db.scalar(select(DcaAlertSettings).where(*tenant_filters(db, DcaAlertSettings)))


def effective_policy(db: Session):
    row = stored_policy(db)
    if row is not None:
        return row
    # New tenant-wide defaults; unscoped legacy test sessions keep their old contract.
    return SimpleNamespace(up_min_level=3, down_max_level=1) if db.info.get("tenant_id") is not None else None


def settings_view(db: Session) -> dict:
    row = stored_policy(db)
    count = db.scalar(select(func.count(DcaAlertOverride.id)).where(*tenant_filters(db, DcaAlertOverride))) or 0
    settings = get_settings()
    return {
        "configured": row is not None,
        "up_min_level": row.up_min_level if row else 3,
        "down_max_level": row.down_max_level if row else 1,
        "legacy_override_count": count,
        "legacy_min_level": int(settings.dca_alert_min_level),
        "alerts_enabled": bool(settings.dca_alerts_enabled),
        "trims_enabled": bool(settings.dca_alert_trims),
    }


def save_policy(db: Session, up_min_level: int, down_max_level: int) -> dict:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise ValueError("Tenant identity required")
    if any(type(v) is not int or not 0 <= v <= 4 for v in (up_min_level, down_max_level)):
        raise ValueError("DCA level must be 0..4")
    row = stored_policy(db)
    if row is None:
        row = DcaAlertSettings(tenant_id=tenant_id)
        db.add(row)
    row.up_min_level = up_min_level
    row.down_max_level = down_max_level
    # Deliberately do not delete or update DcaAlertOverride.
    db.commit()
    return settings_view(db)
