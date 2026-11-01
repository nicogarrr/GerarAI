"""Avisos de proximos resultados (7/1/0 dias) sobre el pipeline de alertas. Sin red."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.models import AlertDelivery, Company, EarningsDate, ResearchAlert, Tenant, WatchItem
from app.models.entities import Base
from app.services import earnings_alert_copy
from app.services import earnings_reminders as er
from app.services.outbound_alerts import EVENT_TYPES, event_type

NOW = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)  # lunes
TODAY = NOW.date()


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("EARNINGS_ALERTS_ENABLED", "true")
    monkeypatch.setenv("EARNINGS_ALERT_CHANNELS", "in_app,email")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t-earn", name="t"))
        session.commit()
        session.info.update(tenant_id=1, user_id="u-1")
        yield session


def _watch(db, ticker, name=None, exchange="NYSE", currency="USD"):
    db.add(Company(ticker=ticker, name=name or f"{ticker} Inc", exchange=exchange, currency=currency,
                   company_type="research_candidate", valuation_model="unassigned"))
    db.add(WatchItem(symbol=ticker, company=ticker, tenant_id=1))
    db.commit()


def _row(db, ticker, days, *, confirmed=True, session=None, source="yahoo", label="Yahoo Finance (calendarEvents)", url="https://finance.yahoo.com/quote/X"):
    db.add(EarningsDate(ticker=ticker, event_date=TODAY + timedelta(days=days), session=session,
                        confirmed=confirmed, source=source, source_label=label, source_url=url,
                        fetched_at=NOW))
    db.commit()


def _alerts(db):
    return db.scalars(select(ResearchAlert).where(ResearchAlert.alert_type == "earnings_reminder")).all()


def test_event_type_registered_and_mapped(db):
    assert "earnings" in EVENT_TYPES
    row = ResearchAlert(tenant_id=1, alert_type="earnings_reminder", title="t", message="m", fingerprint="x")
    assert event_type(db, row) == "earnings"


def test_windows_7_1_0_days_and_idempotency(db):
    _watch(db, "ZZA")
    _watch(db, "ZZB")
    _watch(db, "ZZC")
    _row(db, "ZZA", 7, session="pre_market")
    _row(db, "ZZB", 1)
    _row(db, "ZZC", 0, session="after_market")
    stats = er.emit_earnings_reminders(db, now=NOW)
    assert stats["created"] == 3 and stats["existing"] == 0 and not stats["errors"]
    by_ticker = {a.title.split()[0]: a for a in _alerts(db)}
    assert by_ticker["ZZA"].metadata_["earnings"]["window"] == "week"
    assert by_ticker["ZZA"].severity == "low"
    assert by_ticker["ZZB"].metadata_["earnings"]["window"] == "day"
    assert by_ticker["ZZB"].severity == "medium"
    assert by_ticker["ZZC"].metadata_["earnings"]["window"] == "today"
    assert by_ticker["ZZC"].severity == "high"
    # Reejecucion el mismo dia: no repite ningun aviso.
    second = er.emit_earnings_reminders(db, now=NOW + timedelta(hours=2))
    assert second["created"] == 0 and second["existing"] == 3
    assert len(_alerts(db)) == 3


def test_no_alert_without_due_window_or_without_date(db):
    _watch(db, "ZZD")
    _row(db, "ZZD", 3)  # fuera de ventana
    _watch(db, "ZZE")   # sin fecha: nunca se inventa
    stats = er.emit_earnings_reminders(db, now=NOW)
    assert stats["created"] == 0 and _alerts(db) == []


def test_requires_tenant(db):
    db.info.clear()
    with pytest.raises(ValueError):
        er.emit_earnings_reminders(db, now=NOW)


def test_disabled_flag_emits_nothing(db, monkeypatch):
    monkeypatch.setenv("EARNINGS_ALERTS_ENABLED", "false")
    get_settings.cache_clear()
    _watch(db, "ZZF")
    _row(db, "ZZF", 1)
    stats = er.emit_earnings_reminders(db, now=NOW)
    assert stats == {"enabled": False, "created": 0, "existing": 0, "alert_ids": [], "errors": []}
    assert _alerts(db) == []


def test_message_truthful_estimated_session_source_and_origin(db):
    _watch(db, "ZZG", name="Zeta Global")
    _row(db, "ZZG", 1, confirmed=False, session="after_market")
    er.emit_earnings_reminders(db, now=NOW)
    alert = _alerts(db)[0]
    assert alert.title == "ZZG presenta resultados mañana"
    assert "Zeta Global" in alert.message
    assert "3 nov 2026" in alert.message
    assert "tras el cierre" in alert.message
    assert "Fecha estimada por la fuente; puede cambiar" in alert.message
    assert "Fuente: Yahoo Finance (calendarEvents)" in alert.message
    assert "https://finance.yahoo.com/quote/X" in alert.message
    assert "Tu watchlist" in alert.message
    # La fuente no publica hora: ninguna se inventa.
    assert ":00" not in alert.message
    # Sin SMTP configurado el canal "email" no se anuncia: solo in_app.
    assert alert.channels == ["in_app"]
    delivery = db.scalar(select(AlertDelivery).where(AlertDelivery.alert_id == alert.id,
                                                     AlertDelivery.channel == "email"))
    assert delivery is None


def test_email_channel_only_with_smtp_configured(db, monkeypatch):
    """Con SMTP configurado, el canal "email" se anuncia y persiste su entrega."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "alertas@example.test")
    monkeypatch.setenv("ALERT_EMAIL_TO", "nico@example.test")
    get_settings.cache_clear()

    import app.services.notification_service as ns

    # Sin red: el envio real queda fuera del test.
    monkeypatch.setattr(ns, "send_email", lambda settings, content: {"status": "delivered", "error": None})
    _watch(db, "ZZM")
    _row(db, "ZZM", 1)
    er.emit_earnings_reminders(db, now=NOW)
    alert = _alerts(db)[0]
    assert alert.channels == ["in_app", "email"]
    # Intencion de entrega durable para el canal externo.
    delivery = db.scalar(select(AlertDelivery).where(AlertDelivery.alert_id == alert.id,
                                                     AlertDelivery.channel == "email"))
    assert delivery is not None


def test_message_confirmed_and_unknown_confirmation_wording(db):
    _watch(db, "ZZH")
    _watch(db, "ZZI")
    _row(db, "ZZH", 0, confirmed=True, session=None)
    _row(db, "ZZI", 0, confirmed=None)
    er.emit_earnings_reminders(db, now=NOW)
    by_meta = {a.metadata_["earnings"]["ticker"]: a for a in _alerts(db)}
    assert "Fecha confirmada por la fuente" in by_meta["ZZH"].message
    assert "La fuente no indica si la fecha esta confirmada" in by_meta["ZZI"].message
    assert "antes de la apertura" not in by_meta["ZZH"].message  # sin franja no se pinta


def test_portfolio_origin_wins_over_watchlist(db):
    from app.models import Position

    db.add(Company(ticker="ZZJ", name="ZZJ Inc", exchange="NYSE", currency="USD",
                   company_type="research_candidate", valuation_model="unassigned"))
    db.commit()
    company = db.scalar(select(Company).where(Company.ticker == "ZZJ"))
    db.add(Position(tenant_id=1, company_id=company.id, quantity=3))
    db.commit()
    _row(db, "ZZJ", 7)
    er.emit_earnings_reminders(db, now=NOW)
    alert = _alerts(db)[0]
    assert "Tu cartera" in alert.message
    assert alert.company_id == company.id


def test_market_today_uses_market_timezone(db, monkeypatch):
    """Una fecha 'mañana' en Tokio no debe avisar un dia antes por culpa de UTC."""
    monkeypatch.setattr(er, "yahoo_symbol", lambda company: "7203.T")
    _watch(db, "7203", name="Toyota")
    _row(db, "7203", 0)  # 2 nov: hoy UTC, pero en Tokio ya es de dia siguiente a las 07:00 UTC
    late = datetime(2026, 11, 2, 20, 0, tzinfo=UTC)  # en Tokio ya es 3 nov 05:00
    stats = er.emit_earnings_reminders(db, now=late)
    # El 2 nov ya paso en Tokio y el 3 nov no esta en ventana "today" (days_until=0 respecto al 3).
    assert stats["created"] == 0
    # A las 15:00 UTC del 1 nov (medianoche del 2 en Tokio) SI es "hoy" alli.
    first = er.emit_earnings_reminders(db, now=datetime(2026, 11, 1, 15, 30, tzinfo=UTC))
    assert first["created"] == 1
    assert _alerts(db)[0].title == "7203 presenta resultados hoy"


def test_channels_from_settings(db, monkeypatch):
    monkeypatch.setenv("EARNINGS_ALERT_CHANNELS", "in_app")
    get_settings.cache_clear()
    _watch(db, "ZZK")
    _row(db, "ZZK", 1)
    er.emit_earnings_reminders(db, now=NOW)
    assert _alerts(db)[0].channels == ["in_app"]


def test_stale_row_never_alerts(db):
    """Una fecha automatica sin renovar en 3+ dias no es fiable: no se avisa."""
    _watch(db, "ZZL")
    db.add(EarningsDate(ticker="ZZL", event_date=TODAY + timedelta(days=1), confirmed=True,
                        source="yahoo", source_label="Yahoo Finance (calendarEvents)",
                        fetched_at=NOW - timedelta(days=5)))
    db.commit()
    stats = er.emit_earnings_reminders(db, now=NOW)
    assert stats["created"] == 0


def test_manual_row_wins_and_is_used(db):
    _watch(db, "ZZM")
    _row(db, "ZZM", 3)  # la automatica cae fuera de ventana
    db.add(EarningsDate(ticker="ZZM", event_date=TODAY + timedelta(days=1), source="manual",
                        source_label="Comunicado de la empresa", source_url="https://empresa.test/resultados",
                        confirmed=None, fetched_at=NOW - timedelta(days=30)))
    db.commit()
    er.emit_earnings_reminders(db, now=NOW)
    alert = _alerts(db)[0]
    earnings = alert.metadata_["earnings"]
    assert earnings["event_date"] == (TODAY + timedelta(days=1)).isoformat()
    assert earnings["source"] == "Comunicado de la empresa"
    assert "https://empresa.test/resultados" in alert.message


def test_email_copy_subject_text_html():
    earnings = {
        "ticker": "ASTS", "company_name": "AST SpaceMobile", "origin": "cartera",
        "event_date": "2026-11-03", "session": "after_market", "fiscal_label": "Q3 2026",
        "confirmed": False, "source": "Yahoo Finance (calendarEvents)",
        "source_url": "https://finance.yahoo.com/quote/ASTS", "window": "day",
        "rule_version": er.VERSION,
    }
    content = earnings_alert_copy.email_content(earnings)
    assert content.subject == "ASTS presenta resultados mañana · AST SpaceMobile"
    assert "3 nov 2026" in content.text and "tras el cierre" in content.text
    assert "puede cambiar" in content.text
    assert "https://finance.yahoo.com/quote/ASTS" in content.text
    assert "Q3 2026" in content.text
    assert 'lang="es"' in content.html and "AST SpaceMobile" in content.html
    assert "https://finance.yahoo.com/quote/ASTS" in content.html
    # Sin franja ni trimestre: no se pintan.
    minimal = earnings_alert_copy.email_content({**earnings, "session": None, "fiscal_label": None})
    assert "Franja" not in minimal.text and "Q3 2026" not in minimal.text


def test_dispatch_email_uses_earnings_template(db, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "alertas@example.test")
    monkeypatch.setenv("ALERT_EMAIL_TO", "nico@example.test")
    get_settings.cache_clear()
    sent = {}

    def fake_send(settings, content):
        sent["content"] = content
        return {"status": "delivered", "error": None}

    import app.services.notification_service as ns

    monkeypatch.setattr(ns, "send_email", fake_send)
    _watch(db, "ZZN", name="Zeta Norte")
    _row(db, "ZZN", 0, session="pre_market")
    er.emit_earnings_reminders(db, now=NOW)
    content = sent["content"]
    assert content.subject.startswith("ZZN presenta resultados hoy")
    assert "antes de la apertura" in content.text
    assert "Zeta Norte" in (content.html or "")


def test_actor_on_alerts_queue():
    from app.workers import dramatiq_app

    assert dramatiq_app.dispatch_earnings_reminders.queue_name == dramatiq_app.ALERT_QUEUE_NAME == "alerts"


def test_scheduler_registers_daily_reminders():
    from apscheduler.schedulers.blocking import BlockingScheduler

    from app.workers.scheduler import build_scheduler

    scheduler = build_scheduler()
    assert isinstance(scheduler, BlockingScheduler)
    job = scheduler.get_job("earnings_reminders_daily")
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "7" and fields["minute"] == "5"


def test_race_on_fingerprint_counts_as_existing(db, monkeypatch):
    _watch(db, "ZZR")
    _row(db, "ZZR", 1)
    er.emit_earnings_reminders(db, now=NOW)
    monkeypatch.setattr(db, "scalar", lambda *_a, **_k: None)  # simula la carrera
    out = er.emit_earnings_reminders(db, now=NOW)
    assert out["created"] == 0 and out["existing"] == 1


def test_dispatch_failure_is_recorded_and_alert_kept(db, monkeypatch):
    from app.services import notification_service as ns

    monkeypatch.setattr(ns.NotificationService, "dispatch",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp caido")))
    _watch(db, "ZZS")
    _row(db, "ZZS", 0)
    out = er.emit_earnings_reminders(db, now=NOW)
    assert out["created"] == 1 and len(out["errors"]) == 1
    assert len(_alerts(db)) == 1  # la alerta queda en la app aunque falle el canal


def test_no_followed_companies_and_utc_fallback(db):
    assert er.due_reminders(db, NOW) == []
    assert er._market_today(None, NOW) == NOW.date()


def test_earnings_reminders_are_opt_in_by_default(monkeypatch):
    from pathlib import Path

    from app.core.config import Settings

    monkeypatch.delenv("EARNINGS_ALERTS_ENABLED", raising=False)
    assert Settings(_env_file=None).earnings_alerts_enabled is False
    example = Path(__file__).resolve().parents[2] / "docker.env.example"
    assert "EARNINGS_ALERTS_ENABLED=false" in example.read_text()
    assert "EARNINGS_ALERTS_ENABLED=true" not in example.read_text()


def _english(db, monkeypatch):
    """Usuario con inglés guardado en Ajustes y generación multidioma encendida."""
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    db.get(Tenant, 1).metadata_ = {"language": "en"}
    db.commit()


def test_reminder_uses_saved_english_language(db, monkeypatch):
    _english(db, monkeypatch)
    _watch(db, "ZZG", name="Zeta Global")
    _row(db, "ZZG", 1, confirmed=False, session="after_market")
    er.emit_earnings_reminders(db, now=NOW)
    alerts = _alerts(db)
    assert [a.title for a in alerts] == ["ZZG reports earnings tomorrow"]
    message = alerts[0].message
    for text in ("Date: 3 Nov 2026", "after the close (session published by the source; no exact time)",
                 "Date status: Date estimated by the source; it may change", "Tracked from: Your watchlist",
                 "Source: Yahoo Finance (calendarEvents)", "Source link: https://finance.yahoo.com/quote/X",
                 "Earnings calendar notice; not financial advice."):
        assert text in message
    assert "Fuente" not in message and "mañana" not in message
    assert alerts[0].metadata_["language"] == "en"


def test_reminder_stays_spanish_without_saved_language_or_flag(db, monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    _watch(db, "ZZG")
    _row(db, "ZZG", 1)
    er.emit_earnings_reminders(db, now=NOW)
    alert = _alerts(db)[0]
    assert alert.title == "ZZG presenta resultados mañana"
    assert "language" not in alert.metadata_


def test_reminder_email_in_english_and_dispatch_reads_language(monkeypatch):
    from types import SimpleNamespace

    from app.services import notification_service as ns

    earnings = {"ticker": "ZZG", "event_date": "2026-11-03", "window": "day", "confirmed": True,
                "source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/X"}
    content = earnings_alert_copy.email_content(earnings, "en")
    assert content.subject == "ZZG reports earnings tomorrow"
    assert '<html lang="en">' in content.html and ">Source: <a" in content.html.replace("\n", "")
    assert "GerarAI&#x27;s earnings calendar" in content.html
    week = earnings_alert_copy.title({**earnings, "window": "week"}, "en")
    assert week == "ZZG reports earnings on 3 Nov 2026"
    assert earnings_alert_copy.title({**earnings, "window": "week"}) == "ZZG presenta resultados el 3 nov 2026"
    sent = []
    monkeypatch.setattr(ns, "send_email", lambda settings, c: sent.append(c) or {"status": "delivered"})
    for meta in ({"earnings": earnings, "language": "en"}, {"earnings": earnings}):
        ns.NotificationService()._dispatch_email(None, SimpleNamespace(alert_type="earnings_reminder", metadata_=meta), {})
    assert [c.subject for c in sent] == ["ZZG reports earnings tomorrow", "ZZG presenta resultados mañana"]
