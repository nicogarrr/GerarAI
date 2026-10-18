import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import telegram_link as routes
from app.api.routes.alerts import TelegramSubscriptionIn, set_telegram_subscription
from app.models.entities import TelegramChatBinding, TelegramLinkChallenge
from app.services import notification_service
from app.services.telegram_link import confirm_link, receive_bot_link, start_link, verify_relay
from tests.test_outbound_alerts import alert, db  # noqa: F401


def token_of(start):
    return start["command"].split()[1]


def test_arbitrary_foreign_chat_rejected(db):
    with pytest.raises(HTTPException) as exc:
        set_telegram_subscription("thesis_broken", TelegramSubscriptionIn(enabled=True, chat_id="99999"), db)
    assert exc.value.status_code == 403
    assert db.scalar(select(TelegramChatBinding)) is None


def test_owner_bot_proof_owner_confirm_and_single_use(db):
    link = start_link(db)
    with pytest.raises(HTTPException):
        confirm_link(db, link["challenge_id"], "12345")
    receive_bot_link(db, token_of(link), "12345")
    with pytest.raises(HTTPException):
        confirm_link(db, link["challenge_id"], "99999")
    assert confirm_link(db, link["challenge_id"], "12345")["verified"]
    set_telegram_subscription("thesis_broken", TelegramSubscriptionIn(enabled=True, chat_id="12345"), db)
    with pytest.raises(HTTPException):
        receive_bot_link(db, token_of(link), "99999")
    with pytest.raises(HTTPException):
        confirm_link(db, link["challenge_id"], "12345")


def test_cross_user_confirmation_and_expiry_blocked(db):
    link = start_link(db)
    receive_bot_link(db, token_of(link), "12345")
    db.info["user_id"] = "stranger"
    with pytest.raises(HTTPException) as exc:
        confirm_link(db, link["challenge_id"], "12345")
    assert exc.value.status_code == 404
    db.info["user_id"] = "owner"
    row = db.get(TelegramLinkChallenge, link["challenge_id"])
    row.expires_at = datetime.now(UTC)-timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException):
        confirm_link(db, link["challenge_id"], "12345")


def test_unknown_alert_never_uses_global_destination(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notification_service, "get_settings", lambda: SimpleNamespace(telegram_chat_id="99999", telegram_enabled=True))
    monkeypatch.setattr(notification_service.NotificationService, "_dispatch_telegram", lambda *args: calls.append(args))
    record = alert(db, "unknown_type")
    record.channels = ["telegram"]
    result = notification_service.NotificationService().dispatch(db, record)
    assert result["telegram"]["status"] == "skipped" and calls == []


def test_adapter_no_global_fallback(monkeypatch):
    settings = SimpleNamespace(telegram_bot_token="test-only", telegram_enabled=True, telegram_chat_id="99999")
    result = notification_service.NotificationService()._dispatch_telegram(settings, {})
    assert result["status"] == "not_configured"


def test_relay_authentication_and_private_sender(monkeypatch):
    secret = "test-only-"*8
    body = b'{"token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","chat_id":"12345","telegram_user_id":"12345","chat_type":"private"}'
    stamp = str(int(time.time()))
    sig = hmac.new(secret.encode(), stamp.encode()+b"."+body, hashlib.sha256).hexdigest()
    verify_relay(secret, body, stamp, sig)
    for invalid in ("", "0"*64):
        with pytest.raises(HTTPException): verify_relay(secret, body, stamp, invalid)
    with pytest.raises(HTTPException): verify_relay(secret, body+b" ", stamp, sig)
    with pytest.raises(HTTPException): verify_relay(secret, body, "1", sig)
    app = FastAPI()
    app.include_router(routes.relay_router)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(telegram_link_secret=secret))
    client = TestClient(app)
    assert client.post("/api/telegram/link-proof", content=body, headers={"Content-Type":"application/json"}).status_code == 401
    wrong = body.replace(b'"private"', b'"group"')
    signature = hmac.new(secret.encode(), stamp.encode()+b"."+wrong, hashlib.sha256).hexdigest()
    assert client.post("/api/telegram/link-proof", content=wrong, headers={"Content-Type":"application/json", "X-Asistenta-Timestamp":stamp,"X-Asistenta-Signature":signature}).status_code == 403


def test_changed_binding_disables_old_subscriptions(db):
    from app.models import AlertSubscription
    from app.services.outbound_alerts import subscription_for

    first = start_link(db)
    receive_bot_link(db, token_of(first), "12345")
    confirm_link(db, first["challenge_id"], "12345")
    set_telegram_subscription("thesis_broken", TelegramSubscriptionIn(enabled=True, chat_id="12345"), db)
    record = alert(db)
    assert subscription_for(db, record)
    second = start_link(db)
    receive_bot_link(db, token_of(second), "67890")
    confirm_link(db, second["challenge_id"], "67890")
    assert not db.scalar(select(AlertSubscription)).enabled
    assert subscription_for(db, record) is None
    with pytest.raises(HTTPException):
        set_telegram_subscription("thesis_broken", TelegramSubscriptionIn(enabled=True, chat_id="12345"), db)


def test_successful_authenticated_relay_and_replay(db, monkeypatch):
    secret = "relay-test-only-"*4
    challenge = start_link(db)
    # Real relay has no owner identity: the signed one-use token resolves it.
    db.info.clear()
    import json
    body = json.dumps({"token":token_of(challenge), "chat_id":"12345", "telegram_user_id":"12345", "chat_type":"private"}).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode()+b"."+body, hashlib.sha256).hexdigest()
    # Route and proof use this test's session; no network/provider calls.
    class Context:
        def __enter__(self): return db
        def __exit__(self, *args): pass
    monkeypatch.setattr(routes, "SessionLocal", Context)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(telegram_link_secret=secret))
    app = FastAPI()
    app.include_router(routes.relay_router)
    client = TestClient(app)
    headers = {"Content-Type":"application/json", "X-Asistenta-Timestamp":stamp, "X-Asistenta-Signature":signature}
    assert client.post("/api/telegram/link-proof", content=body, headers=headers).status_code == 200
    assert client.post("/api/telegram/link-proof", content=body, headers=headers).status_code == 409



def test_cnmv_backward_stale_future_and_same_date_blocked(db):
    from app.models import Company, Position, ResearchAlert
    from app.services.short_positions_service import emit_shorts_increase
    company = Company(ticker="CNMV", name="CNMV", exchange="BME", company_type="compounders", valuation_model="dcf")
    db.add(company)
    db.commit()
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime(2026, 10, 8, tzinfo=UTC)
    old = {"source":"CNMV", "public_total_percent":.5, "positions":[{"holder":"A", "percent":.5, "position_date":"2026-09-30"}]}
    for stamp in ("2020-01-01", "2026-09-30", "2026-10-09", "bad-date"):
        new = {"source":"CNMV", "public_total_percent":.8, "positions":[{"holder":"A", "percent":.8, "position_date":stamp}], "source_url":"https://www.cnmv.es/"}
        emit_shorts_increase(db, company, old, new, now)
        assert db.scalar(select(ResearchAlert)) is None
    old["positions"][0]["position_date"] = "2020-01-01"
    new["positions"][0]["position_date"] = "2020-02-01"
    emit_shorts_increase(db, company, old, new, now)
    assert db.scalar(select(ResearchAlert)) is None
    old["positions"][0]["position_date"] = "2026-09-30"
    new["positions"][0]["position_date"] = "2026-10-01"
    emit_shorts_increase(db, company, old, new, now)
    assert "2026-10-01" in db.scalar(select(ResearchAlert)).message
