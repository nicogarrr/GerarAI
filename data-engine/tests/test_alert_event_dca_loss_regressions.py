"""Regresiones: eventos perdidos en cooldown, senal DCA con historia vieja y
alerta DCA perdida entre persistir el nivel y crearla."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Base,
    Company,
    DcaSignalState,
    EarningsRun,
    NewsEvent,
    ResearchAlert,
    Tenant,
    WatchItem,
)
from app.services import dca_signal_service as svc
from app.services.alert_rule_service import AlertRuleService
from tests.test_dca_signal_service import NOW, PARAMS, FakeFetcher, series


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("DCA_ALERT_MIN_LEVEL", "2")
    monkeypatch.setenv("DCA_ALERT_TRIMS", "false")
    monkeypatch.setenv("DCA_ALERTS_ENABLED", "true")
    monkeypatch.setenv("DCA_ALERT_CHANNELS", "in_app")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t-reg", name="t"))
        session.commit()
        session.info["tenant_id"] = 1
        session.info["user_id"] = "u-1"
        yield session
    get_settings.cache_clear()


def _company(db):
    c = Company(ticker="DEMO", name="Synthetic", exchange="NASDAQ", currency="USD", sector="x",
                industry="x", company_type="x", valuation_model="x", special_sources=[],
                special_risks=[], factor_tags=[])
    db.add(c)
    db.commit()
    return c


def _cooldown_rule(db, c, rule_type):
    s = AlertRuleService()
    r = s.create(db, c, rule_type=rule_type, operator=">", value=0, cooldown_seconds=3600)
    now = datetime.now(UTC)
    r.last_triggered_at = now - timedelta(minutes=10)
    r.last_evaluated_at = now - timedelta(minutes=5)
    r.trigger_count = 1
    db.commit()
    return s, r


def _news(db, c, title, minutes_ago=1):
    db.add(NewsEvent(company_id=c.id, title=title, url=f"https://example.invalid/{title}", source="s",
                     summary="", created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago)))
    db.commit()


def _alerts_of(db, alert_type):
    return list(db.scalars(select(ResearchAlert).where(ResearchAlert.alert_type == alert_type)))


def test_news_event_during_cooldown_alerts_after_cooldown(db):
    c = _company(db)
    s, r = _cooldown_rule(db, c, "news")
    _news(db, c, "event-in-cooldown")
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        first = s.evaluate(db, r)
        assert first["matched"] and first["cooldown_active"]
        assert not _alerts_of(db, "news")
        # Reevaluar aun en cooldown no consume el evento.
        assert s.evaluate(db, r)["matched"]
        r.last_triggered_at = datetime.now(UTC) - timedelta(hours=2)
        db.commit()
        second = s.evaluate(db, r)
    assert second["status"] == "triggered"
    assert len(_alerts_of(db, "news")) == 1
    # Consumido: no vuelve a avisar del mismo evento.
    r.last_triggered_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        third = s.evaluate(db, r)
    assert not third["matched"]
    assert len(_alerts_of(db, "news")) == 1


def test_news_burst_in_cooldown_yields_one_alert_for_latest(db):
    c = _company(db)
    s, r = _cooldown_rule(db, c, "news")
    _news(db, c, "older", minutes_ago=2)
    _news(db, c, "newest", minutes_ago=1)
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        s.evaluate(db, r)
        r.last_triggered_at = datetime.now(UTC) - timedelta(hours=2)
        db.commit()
        s.evaluate(db, r)
    alerts = _alerts_of(db, "news")
    assert len(alerts) == 1 and "newest" in alerts[0].message


def test_earnings_run_during_cooldown_alerts_after_cooldown(db):
    c = _company(db)
    s, r = _cooldown_rule(db, c, "earnings")
    db.add(EarningsRun(company_id=c.id, fiscal_year=2026, fiscal_quarter="Q3", status="completed",
                       created_at=datetime.now(UTC) - timedelta(minutes=1)))
    db.commit()
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        assert s.evaluate(db, r)["cooldown_active"]
        r.last_triggered_at = datetime.now(UTC) - timedelta(hours=2)
        db.commit()
        assert s.evaluate(db, r)["status"] == "triggered"
    assert len(_alerts_of(db, "earnings")) == 1


def test_event_without_cooldown_not_realerted(db):
    c = _company(db)
    s = AlertRuleService()
    r = s.create(db, c, rule_type="news", operator=">", value=0, cooldown_seconds=0)
    r.created_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    _news(db, c, "once")
    with patch("app.services.jev_triage_service.classify_urgency_sync", return_value=None):
        assert s.evaluate(db, r)["status"] == "triggered"
        assert s.evaluate(db, r)["status"] == "evaluated"
    assert len(_alerts_of(db, "news")) == 1


def _watch(db):
    db.add(WatchItem(tenant_id=1, symbol="DEMO"))
    db.commit()


def _run(db, f):
    return svc.evaluate_watchlist(db, fetcher=f, now=NOW, today=NOW.date(), params=PARAMS)


def _seed(db, f):
    """Primera evaluacion en 1X: solo guarda el estado (sin aviso)."""
    f.set("DEMO", series(100))
    assert _run(db, f)["alerted"] == []


def test_stale_history_does_not_emit_or_persist_signal(db):
    _watch(db)
    f = FakeFetcher()
    f.set("DEMO", series(55, end=(2020, 1)))
    out = _run(db, f)
    assert out["evaluated"] == 0 and not out["alerted"]
    assert out["skipped"][0]["reason"] == "datos_desactualizados"
    assert out["skipped"][0]["last_price_date"] == "2020-01-15"
    assert db.scalar(select(DcaSignalState)) is None
    assert db.query(ResearchAlert).count() == 0


def test_fresh_history_still_evaluates(db):
    _watch(db)
    f = FakeFetcher()
    _seed(db, f)
    f.set("DEMO", series(55))
    out = _run(db, f)
    assert out["evaluated"] == 1 and out["alerted"][0]["level"] == 4


def test_failure_before_alert_insert_does_not_persist_level_and_retry_alerts(db):
    _watch(db)
    f = FakeFetcher()
    _seed(db, f)
    f.set("DEMO", series(70))
    with patch.object(svc, "_emit_alert_row", side_effect=RuntimeError("crash")):
        with pytest.raises(RuntimeError):
            _run(db, f)
    assert db.scalar(select(DcaSignalState)).level == 1
    assert db.query(ResearchAlert).count() == 0
    out = _run(db, f)
    assert [a["level"] for a in out["alerted"]] == [3]
    assert db.query(ResearchAlert).count() == 1
    state = db.scalar(select(DcaSignalState))
    assert state.level == 3 and state.last_alerted_level == 3
    # El mes sigue deduplicado: otra pasada no repite.
    assert _run(db, f)["alerted"] == []
    assert db.query(ResearchAlert).count() == 1


def test_dispatch_failure_keeps_alert_and_state(db):
    _watch(db)
    f = FakeFetcher()
    _seed(db, f)
    f.set("DEMO", series(70))
    with patch("app.services.notification_service.NotificationService.dispatch", side_effect=RuntimeError("chan")):
        out = _run(db, f)
    assert out["alerted"][0]["deliveries"] == {"error": "dispatch_error"}
    assert db.query(ResearchAlert).count() == 1
    assert db.scalar(select(DcaSignalState)).last_alerted_level == 3


def test_dca_external_channel_intent_survives_dispatch_failure_and_reconciles(db, monkeypatch):
    """Despacho que falla ANTES de crear filas de canal: la intencion de entrega
    ya es durable (fila pending) y el reconciliador envia el canal pendiente."""
    from types import SimpleNamespace

    from sqlalchemy import update

    from app.models.entities import AlertDelivery
    from app.services import notification_service

    monkeypatch.setenv("DCA_ALERT_CHANNELS", "in_app,email")
    get_settings.cache_clear()
    _watch(db)
    f = FakeFetcher()
    _seed(db, f)
    f.set("DEMO", series(70))
    with patch("app.services.notification_service.NotificationService.dispatch", side_effect=RuntimeError("boom")):
        out = _run(db, f)
    alert_id = out["alerted"][0]["alert_id"]
    rows = {r.channel: r.status for r in db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == alert_id))}
    assert rows == {"in_app": "delivered", "email": "pending"}

    posts: list[str] = []

    class _Client:
        def __init__(self, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

        def post(self, url, json):
            posts.append(url)
            return SimpleNamespace(raise_for_status=lambda: None)

    settings = SimpleNamespace(
        telegram_enabled=False, telegram_bot_token=None, telegram_chat_id=None,
        telegram_api_base_url="https://api.telegram.org", telegram_timeout_seconds=10,
        alert_email_webhook_url="https://hooks.example/email", alert_push_webhook_url=None,
    )
    monkeypatch.setattr(notification_service.httpx, "Client", _Client)
    monkeypatch.setattr(notification_service, "get_settings", lambda: settings)
    monkeypatch.setattr(notification_service, "smtp_configured", lambda _s: False)
    # Antes del TTL no se reclama (el despacho original puede seguir en curso).
    assert notification_service.NotificationService().reconcile_stale_deliveries(db)["candidates"] == 0
    db.execute(update(AlertDelivery).where(AlertDelivery.alert_id == alert_id).values(
        updated_at=datetime.now(UTC) - timedelta(seconds=notification_service.STALE_CLAIM_SECONDS + 5)))
    db.commit()
    stats = notification_service.NotificationService().reconcile_stale_deliveries(db)
    assert stats["candidates"] == 1 and stats["redispatched"] == 1
    assert posts == ["https://hooks.example/email"]
    rows = {r.channel: r.status for r in db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == alert_id))}
    assert rows == {"in_app": "delivered", "email": "delivered"}
