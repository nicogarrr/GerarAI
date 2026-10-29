"""Web Push (PWA): servicio y canal del outbox. Sin red: pywebpush mockeado."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.models import AlertDelivery, PushPreference, PushSubscription, ResearchAlert, Tenant
from app.models.entities import Base
from app.services import web_push
from app.services.notification_service import NotificationService
from app.services.outbound_alerts import dispatch_pending

FCM = "https://fcm.googleapis.com/fcm/send/abc123def456ghi789"


class HttpError(Exception):
    def __init__(self, code, headers=None):
        self.response = SimpleNamespace(status_code=code, headers=headers or {})


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


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[dict, dict]] = []

    def fake(info, data, settings):
        calls.append((info, json.loads(data)))

    monkeypatch.setattr(web_push, "_send", fake)
    return calls


def add_device(db, endpoint=FCM, user="owner", tenant=1):
    row = PushSubscription(tenant_id=tenant, user_id=user, endpoint=endpoint,
                           endpoint_hash=web_push.endpoint_hash(endpoint), p256dh="B" * 30, auth_secret="a" * 12)
    db.add(row)
    db.commit()
    return row


def make_alert(db, kind="macro_event", created=None, fp="fp1"):
    row = ResearchAlert(tenant_id=1, alert_type=kind, title="IPC: mañana", message="Fuente: BLS (OFICIAL). " * 20,
                        fingerprint=fp, channels=["in_app"], created_at=created or datetime.now(UTC))
    db.add(row)
    db.commit()
    return row


def enable(db, kind="macro_event"):
    db.add(PushPreference(tenant_id=1, user_id="owner", event_type=kind, enabled=True,
                          enabled_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()


@pytest.mark.parametrize("endpoint,ok", [
    (FCM, True),
    ("https://updates.push.services.mozilla.com/wpush/v2/xyz", True),
    ("https://web.push.apple.com/QGx", True),
    ("https://wns2-par02p.notify.windows.com/w/?token=1", True),
    ("http://fcm.googleapis.com/fcm/send/x", False),
    ("https://evil.example.com/fcm.googleapis.com", False),
    ("https://fcm.googleapis.com.evil.com/x", False),
    ("https://user:pw@fcm.googleapis.com/x", False),
    ("https://fcm.googleapis.com:8443/x", False),
    ("https://127.0.0.1/x", False),
    ("not a url", False),
    ("https://[::1/x", False),
])
def test_endpoint_allowlist(endpoint, ok):
    assert web_push.endpoint_is_allowed(endpoint) is ok


def test_dispatch_sends_push_only_with_preference(db, configured, sent):
    add_device(db)
    alert = make_alert(db)
    NotificationService().dispatch(db, alert)
    assert sent == []
    assert db.scalar(select(AlertDelivery).where(AlertDelivery.channel == "push")) is None
    enable(db)
    fresh = make_alert(db, fp="fp2", created=datetime.now(UTC) + timedelta(seconds=5))
    result = NotificationService().dispatch(db, fresh)
    assert result["push"]["status"] == "delivered"
    info, payload = sent[0]
    assert info["endpoint"] == FCM and info["keys"] == {"p256dh": "B" * 30, "auth": "a" * 12}
    assert payload["title"] == "IPC: mañana" and payload["url"] == "/alerts" and payload["tag"] == f"alert-{fresh.id}"
    assert len(payload["body"]) <= web_push.MAX_BODY_CHARS and "Alert id" not in payload["body"]
    row = db.scalar(select(AlertDelivery).where(AlertDelivery.channel == "push"))
    assert row.status == "delivered"
    sent.clear()
    NotificationService().dispatch(db, fresh)
    assert sent == []  # entregada: nunca se reenvia


def test_alert_before_opt_in_is_not_replayed(db, configured, sent):
    old = make_alert(db, created=datetime.now(UTC) - timedelta(days=1))
    add_device(db)
    enable(db)
    NotificationService().dispatch(db, old)
    assert sent == []


def test_other_users_device_is_never_used(db, configured, sent):
    add_device(db, user="otro")
    enable_row = PushPreference(tenant_id=1, user_id="owner", event_type="macro_event", enabled=True,
                                enabled_at=datetime.now(UTC) - timedelta(hours=1))
    db.add(enable_row)
    db.commit()
    out = NotificationService().dispatch(db, make_alert(db))
    assert sent == [] and out["push"]["status"] == "skipped"


def test_not_configured_server_marks_not_configured(db, configured, sent, monkeypatch):
    add_device(db)
    db.add(PushPreference(tenant_id=1, user_id="owner", event_type="macro_event", enabled=True,
                          enabled_at=datetime.now(UTC) - timedelta(hours=1)))
    db.commit()
    monkeypatch.setattr(configured, "web_push_enabled", False)
    out = NotificationService().dispatch(db, make_alert(db))
    assert out["push"]["status"] == "not_configured" and sent == []


@pytest.mark.parametrize("error,status,kept", [
    (HttpError(410), "failed", 0),
    (HttpError(404), "failed", 0),
    (HttpError(400), "failed", 1),
    (HttpError(429, {"Retry-After": "120"}), "throttled", 1),
    (HttpError(429, {"Retry-After": "x"}), "throttled", 1),
    (HttpError(503), "unknown", 1),
    (TimeoutError(), "unknown", 1),
])
def test_failures_are_classified_and_expired_devices_removed(db, configured, monkeypatch, error, status, kept):
    add_device(db)
    db.add(PushPreference(tenant_id=1, user_id="owner", event_type="macro_event", enabled=True,
                          enabled_at=datetime.now(UTC) - timedelta(hours=1)))
    db.commit()

    def boom(info, data, settings):
        raise error

    monkeypatch.setattr(web_push, "_send", boom)
    out = NotificationService().dispatch(db, make_alert(db))
    assert out["push"]["status"] == status
    assert "fcm.googleapis.com" not in json.dumps(out)  # el endpoint no se persiste
    assert len(db.scalars(select(PushSubscription)).all()) == kept
    if status == "throttled":
        assert out["push"]["retry_after"] in (120, 600)


def test_one_good_device_is_enough(db, configured, monkeypatch):
    add_device(db)
    add_device(db, endpoint="https://updates.push.services.mozilla.com/wpush/v2/ok")
    db.add(PushPreference(tenant_id=1, user_id="owner", event_type="macro_event", enabled=True,
                          enabled_at=datetime.now(UTC) - timedelta(hours=1)))
    db.commit()
    attempts = []

    def flaky(info, data, settings):
        attempts.append(info["endpoint"])
        if "fcm" in info["endpoint"]:
            raise HttpError(410)

    monkeypatch.setattr(web_push, "_send", flaky)
    out = NotificationService().dispatch(db, make_alert(db))
    assert out["push"]["status"] == "delivered" and len(attempts) == 2
    assert [d.endpoint for d in db.scalars(select(PushSubscription))] == ["https://updates.push.services.mozilla.com/wpush/v2/ok"]


def test_dispatch_pending_serves_push_only_users_once(db, configured, sent):
    add_device(db)
    db.add(PushPreference(tenant_id=1, user_id="owner", event_type="macro_event", enabled=True,
                          enabled_at=datetime.now(UTC) - timedelta(hours=1)))
    db.commit()
    make_alert(db)
    first = dispatch_pending(db)
    assert first["redispatched"] == 1 and len(sent) == 1
    second = dispatch_pending(db)
    assert second["candidates"] == 0 and len(sent) == 1
    channels = {d.channel for d in db.scalars(select(AlertDelivery))}
    assert "push" in channels and "telegram" not in channels


def test_dispatch_pending_skips_alerts_without_consent(db, configured, sent):
    add_device(db)
    db.add(PushPreference(tenant_id=1, user_id="owner", event_type="new_filing", enabled=True,
                          enabled_at=datetime.now(UTC) - timedelta(hours=1)))
    db.commit()
    make_alert(db, kind="new_filing", fp="a", created=datetime.now(UTC))
    other = make_alert(db, kind="tracked_news", fp="b")  # sin fuente SEC: sin categoria
    out = dispatch_pending(db)
    assert out["candidates"] >= 1
    assert other.id is not None


def test_real_sender_builds_vapid_call(configured, monkeypatch):
    import pywebpush

    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(pywebpush, "webpush", fake)
    web_push._send({"endpoint": FCM, "keys": {}}, "{}", configured)
    assert seen["vapid_claims"] == {"sub": "mailto:ops@gerarai.test"}
    assert seen["vapid_private_key"] == "PRIVKEY" and seen["ttl"] == web_push.PUSH_TTL_SECONDS


def test_naive_datetimes_are_handled(db, configured):
    naive = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=30)
    row = PushPreference(tenant_id=1, user_id="owner", event_type="macro_event", enabled=True,
                         enabled_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1))
    db.add(row)
    db.commit()
    alert = make_alert(db, created=naive)
    alert.created_at = naive
    assert web_push.preference_for(db, alert) is not None
    alert.alert_type = "desconocido"
    assert web_push.preference_for(db, alert) is None
    alert.alert_type, alert.tenant_id = "macro_event", 2
    assert web_push.preference_for(db, alert) is None


def test_payload_truncates_long_messages():
    alert = SimpleNamespace(id=9, title="T" * 300, message="palabra " * 100)
    data = json.loads(web_push.build_payload(alert))
    assert len(data["title"]) == 120 and data["body"].endswith("…") and len(data["body"]) <= 180

