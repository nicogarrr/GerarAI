"""Web Push (PWA): rutas HTTP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import alerts as routes
from app.core.config import get_settings
from app.models import PushPreference, PushSubscription, Tenant
from app.models.entities import Base
from app.services import web_push

FCM = "https://fcm.googleapis.com/fcm/send/abc123def456ghi789"



@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=1, external_id="owner"), Tenant(id=2, external_id="other")])
        session.commit()
        session.info.update(tenant_id=1, user_id="owner")
        yield session
    engine.dispose()


@pytest.fixture
def configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "web_push_enabled", True)
    monkeypatch.setattr(settings, "vapid_public_key", "PUBKEY")
    monkeypatch.setattr(settings, "vapid_private_key", "PRIVKEY")
    monkeypatch.setattr(settings, "vapid_subject", "mailto:ops@gerarai.test")
    return settings


def add_device(db, endpoint=FCM, user="owner", tenant=1):
    row = PushSubscription(tenant_id=tenant, user_id=user, endpoint=endpoint,
                           endpoint_hash=web_push.endpoint_hash(endpoint), p256dh="B" * 30, auth_secret="a" * 12)
    db.add(row)
    db.commit()
    return row


def enable(db, kind):
    db.add(PushPreference(tenant_id=1, user_id="owner", event_type=kind, enabled=True,
                          enabled_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()


def test_config_off_by_default_and_exposes_only_public_key(configured, monkeypatch):
    assert routes.push_config() == {"enabled": True, "public_key": "PUBKEY"}
    monkeypatch.setattr(configured, "web_push_enabled", False)
    assert routes.push_config() == {"enabled": False, "public_key": None}
    monkeypatch.setattr(configured, "web_push_enabled", True)
    monkeypatch.setattr(configured, "vapid_private_key", None)
    assert web_push.is_configured(configured) is False


def test_status_lists_every_event_type_off_by_default(db, configured):
    status = routes.push_status(db)
    assert status["devices"] == 0 and status["enabled"] is True
    kinds = [row["event_type"] for row in status["preferences"]]
    assert "macro_event" in kinds and "dca_levels" in kinds
    assert not any(row["enabled"] for row in status["preferences"])
    add_device(db)
    enable(db, "daily_digest")
    status = routes.push_status(db)
    assert status["devices"] == 1
    assert {r["event_type"]: r["enabled"] for r in status["preferences"]}["daily_digest"] is True



def test_status_requires_verified_identity(db, configured):
    db.info.pop("tenant_id")
    with pytest.raises(HTTPException) as exc:
        routes.push_status(db)
    assert exc.value.status_code == 401
