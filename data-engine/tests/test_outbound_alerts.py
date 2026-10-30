from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes.alerts import (
    TelegramSubscriptionIn,
    list_telegram_subscriptions,
    set_telegram_subscription,
)
from app.models import AlertDelivery, Company, NewsEvent, Position, ResearchAlert, Tenant
from app.models.entities import Base
from app.services import notification_service
from app.services.outbound_alerts import dispatch_pending, event_type, subscription_for
from app.services.short_positions_service import emit_shorts_increase


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="owner"))
        db.commit()
        db.info.update(tenant_id=1, user_id="owner")
        yield db
    engine.dispose()


def alert(db, kind="thesis_broken", created=None):
    row = ResearchAlert(tenant_id=1, alert_type=kind, title="Revisar tesis", message="Afirmación contradicha por evidencia", fingerprint=f"{kind}-{created}", channels=["in_app"], created_at=created or datetime.now(UTC))
    db.add(row)
    db.commit()
    return row


def opt_in(db, kind="thesis_broken"):
    from app.models.entities import TelegramChatBinding
    if db.info.get("user_id") == "owner" and db.scalar(select(TelegramChatBinding)) is None:
        db.add(TelegramChatBinding(user_id="owner", chat_id="12345"))
        db.commit()
    return set_telegram_subscription(kind, TelegramSubscriptionIn(enabled=True, chat_id="12345"), db)


def test_defaults_are_disabled_and_require_identity(db):
    assert all(not r["enabled"] for r in list_telegram_subscriptions(db))
    db.info.pop("user_id")
    with pytest.raises(Exception) as exc:
        opt_in(db)
    assert exc.value.status_code == 401


def test_opt_in_type_owner_and_date_are_all_required(db):
    old = alert(db, created=datetime.now(UTC)-timedelta(days=1))
    opt_in(db)
    fresh = alert(db)
    assert subscription_for(db, old) is None
    assert subscription_for(db, fresh).chat_id == "12345"
    assert subscription_for(db, alert(db, "shorts_rising")) is None
    db.info["user_id"] = "other"
    assert subscription_for(db, fresh) is None
    with pytest.raises(Exception) as exc:
        opt_in(db)
    assert exc.value.status_code == 403


def test_dispatch_dedup_revoke_and_no_global_chat_fallback(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notification_service, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(notification_service.NotificationService, "_dispatch_telegram", lambda self, settings, payload: calls.append(payload) or self._result("delivered"))
    opt_in(db)
    first = alert(db)
    dispatch_pending(db)
    notification_service.NotificationService().dispatch(db, first)
    assert len(calls) == 1 and calls[0]["chat_id"] == "12345"
    assert db.scalar(select(AlertDelivery).where(AlertDelivery.channel == "telegram")).attempts == 1
    set_telegram_subscription("thesis_broken", TelegramSubscriptionIn(enabled=False, chat_id="12345"), db)
    first.channels = ["telegram"]
    notification_service.NotificationService().dispatch(db, first)
    assert len(calls) == 1


def test_types_and_cross_tenant(db):
    assert event_type(db, alert(db, "claim_contradicted")) == "thesis_broken"
    assert event_type(db, alert(db, "insider_big_buy")) == "insiders"
    assert event_type(db, alert(db, "new_filing")) == "new_filing"
    opt_in(db)
    row = alert(db)
    db.refresh(row)
    db.expunge(row)
    row.tenant_id = None
    assert subscription_for(db, row) is None


def test_fresh_short_interest_only_not_volume(db):
    company = Company(ticker="ACME", name="ACME", exchange="NASDAQ", company_type="compounders", valuation_model="dcf")
    db.add(company)
    db.commit()
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    emit_shorts_increase(db, company, {}, {"short_volume_ratio": .9}, now)
    assert db.scalar(select(ResearchAlert)) is None
    payload = {"short_interest": {"previous_short_interest": 100, "short_interest": 130,
                                "settlement_date": now.date().isoformat(), "source_url": "https://www.finra.org/"}}
    emit_shorts_increase(db, company, {}, payload, now)
    emit_shorts_increase(db, company, {}, payload, now)
    db.commit()
    assert len(list(db.scalars(select(ResearchAlert)))) == 1
    payload["short_interest"]["settlement_date"] = (now-timedelta(days=60)).date().isoformat()
    emit_shorts_increase(db, company, {}, payload, now)
    assert len(list(db.scalars(select(ResearchAlert)))) == 1


def test_shorts_alert_requires_tenant_interest(db):
    company = Company(ticker="ZZZ", name="ZZZ", exchange="NASDAQ", company_type="compounders", valuation_model="dcf")
    db.add(company)
    db.commit()
    now = datetime.now(UTC)
    payload = {"short_interest": {"previous_short_interest": 100, "short_interest": 130,
                                "settlement_date": now.date().isoformat(), "source_url": "https://www.finra.org/"}}
    emit_shorts_increase(db, company, {}, payload, now)
    db.commit()
    assert db.scalar(select(ResearchAlert)) is None


def test_bot_api_200_error_is_not_delivery(monkeypatch):
    response = httpx.Response(200, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 900}}, request=httpx.Request("POST", "https://api.telegram.org/"))
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kw): return response
    monkeypatch.setattr(notification_service.httpx, "Client", Client)
    settings = SimpleNamespace(telegram_enabled=True, telegram_bot_token="test-only", telegram_chat_id="wrong", telegram_api_base_url="https://api.telegram.org", telegram_timeout_seconds=10)
    result = notification_service.NotificationService()._dispatch_telegram(settings, {"severity":"high", "title":"Alerta", "message":"Fuente", "company_id":1, "alert_id":1, "chat_id":"12345"})
    assert result["status"] == "throttled" and result["retry_after"] == 900



def test_tracked_sec_news_provenance_not_headline(db):
    news = NewsEvent(title="8-K", metadata_={"connector": "gdelt"})
    db.add(news)
    db.commit()
    row = alert(db, "tracked_news")
    row.metadata_ = {"news_event_id": news.id}
    assert event_type(db, row) is None
    news.metadata_ = {"connector": "sec"}
    db.commit()
    assert event_type(db, row) == "new_filing"


def test_no_starvation_by_old_other_type_events(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notification_service, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(notification_service.NotificationService, "_dispatch_telegram", lambda self, settings, payload: calls.append(payload) or self._result("delivered"))
    opt_in(db)
    alert(db, "shorts_rising")
    row = alert(db)
    dispatch_pending(db, limit=1)
    assert calls[0]["alert_id"] == row.id


def test_cnmv_holder_set_changes_not_total_market(db):
    company = Company(ticker="CNMV", name="CNMV", exchange="BME", company_type="compounders", valuation_model="dcf")
    db.add(company)
    db.commit()
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    now = datetime.now(UTC)
    old = {"source":"CNMV", "public_total_percent":.6, "positions":[{"holder":"A", "percent":.6, "position_date":(now-timedelta(days=1)).date().isoformat()}]}
    new = {"source":"CNMV", "public_total_percent":.8, "positions":[{"holder":"B", "percent":.8, "position_date":now.date().isoformat()}], "source_url":"https://www.cnmv.es/"}
    emit_shorts_increase(db, company, old, new, now)
    assert db.scalar(select(ResearchAlert)) is None
    new["positions"][0]["holder"] = "A"
    emit_shorts_increase(db, company, old, new, now)
    assert db.scalar(select(ResearchAlert)).alert_type == "shorts_rising"



def test_telegram_http_429_body_retry_after():
    response = httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 1200}}, request=httpx.Request("POST", "https://api.telegram.org/"))
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        assert notification_service.NotificationService._extract_retry_after(exc) == 1200


def test_telegram_text_earnings_reminder_is_spanish_without_technical_ids():
    payload = {
        "type": "earnings_reminder",
        "severity": "high",
        "title": "ZZA presenta resultados hoy",
        "message": "ZZA Inc\n\nFecha: 2 nov 2026\nEstado de la fecha: Fecha confirmada por la fuente",
        "ticker": "ZZA",
        "company_id": 7,
        "alert_id": 42,
        "jev_urgency": {},
    }
    text = notification_service.NotificationService._telegram_text(payload)
    assert text == f"{payload['title']}\n{payload['message']}"
    assert "Alert id" not in text and "company id" not in text and "HIGH" not in text


def test_dispatch_pending_redispatches_earnings_with_opt_in(db, monkeypatch):
    calls = []
    monkeypatch.setattr(notification_service, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(notification_service.NotificationService, "_dispatch_telegram", lambda self, settings, payload: calls.append(payload) or self._result("delivered"))
    opt_in(db, "earnings")
    row = alert(db, "earnings_reminder")
    stats = dispatch_pending(db)
    assert stats["redispatched"] == 1 and not stats["errors"]
    assert calls and calls[0]["alert_id"] == row.id


def test_dispatch_pending_skips_earnings_without_valid_binding(db, monkeypatch):
    from app.models.entities import TelegramChatBinding
    calls = []
    monkeypatch.setattr(notification_service, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr(notification_service.NotificationService, "_dispatch_telegram", lambda self, settings, payload: calls.append(payload) or self._result("delivered"))
    opt_in(db, "earnings")
    # El consentimiento exige un chat vinculado vigente: sin el, el aviso de
    # resultados se marca como omitido (sin HTTP) y no reintenta en caliente.
    for binding in db.scalars(select(TelegramChatBinding)).all():
        db.delete(binding)
    db.commit()
    row = alert(db, "earnings_reminder")
    stats = dispatch_pending(db)
    assert stats["redispatched"] == 0 and calls == []
    delivery = db.scalar(select(AlertDelivery).where(
        AlertDelivery.alert_id == row.id, AlertDelivery.channel == "telegram"))
    assert delivery is not None and delivery.status == "skipped"
