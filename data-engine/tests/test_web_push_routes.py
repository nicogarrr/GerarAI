"""Web Push (PWA): rutas HTTP."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import alerts as routes
from app.core.config import get_settings
from app.models import PushSubscription, Tenant
from app.models.entities import Base
from app.services import web_push

FCM = "https://fcm.googleapis.com/fcm/send/abc123def456ghi789"
KEYS = routes.PushKeys(p256dh="B" * 30, auth="a" * 12)


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


def enable(db, kind="macro_event"):
    return routes.set_push_preference(kind, routes.PushPreferenceIn(enabled=True), db)


def test_register_device_validations(db, configured, monkeypatch):
    body = routes.PushSubscriptionIn(endpoint=FCM, keys=KEYS, user_agent="UA")
    assert routes.register_push_device(body, db) == {"registered": True}
    assert routes.register_push_device(body, db) == {"registered": True}  # idempotente
    assert len(db.scalars(select(PushSubscription)).all()) == 1
    with pytest.raises(HTTPException) as exc:
        routes.register_push_device(routes.PushSubscriptionIn(endpoint="https://evil.example.com/" + "x" * 20, keys=KEYS), db)
    assert exc.value.status_code == 422
    db.info["user_id"] = "intruso"
    with pytest.raises(HTTPException) as exc:
        routes.register_push_device(body, db)
    assert exc.value.status_code == 403
    db.info.pop("user_id")
    with pytest.raises(HTTPException) as exc:
        routes.register_push_device(body, db)
    assert exc.value.status_code == 401
    db.info["user_id"] = "owner"
    monkeypatch.setattr(configured, "web_push_enabled", False)
    with pytest.raises(HTTPException) as exc:
        routes.register_push_device(body, db)
    assert exc.value.status_code == 409


def test_remove_device_is_scoped_to_owner(db, configured):
    add_device(db)
    db.info["user_id"] = "otro"
    assert routes.remove_push_device(routes.PushEndpointIn(endpoint=FCM), db) == {"removed": False}
    db.info["user_id"] = "owner"
    assert routes.remove_push_device(routes.PushEndpointIn(endpoint=FCM), db) == {"removed": True}
    assert db.scalar(select(PushSubscription)) is None


def test_preference_needs_config_and_a_device(db, configured, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        enable(db)
    assert exc.value.status_code == 403
    add_device(db)
    assert enable(db) == {"event_type": "macro_event", "enabled": True}
    assert routes.set_push_preference("macro_event", routes.PushPreferenceIn(enabled=False), db)["enabled"] is False
    assert enable(db)["enabled"] is True  # reactivar reutiliza la fila
    monkeypatch.setattr(configured, "web_push_enabled", False)
    with pytest.raises(HTTPException) as exc:
        enable(db, "new_filing")
    assert exc.value.status_code == 409
    db.info.pop("tenant_id")
    with pytest.raises(HTTPException) as exc:
        routes.push_status(db)
    assert exc.value.status_code == 401
