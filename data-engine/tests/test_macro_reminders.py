"""Recordatorios macro T-24 h / T-1 h sobre el pipeline de alertas. Sin red."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services import macro_reminders as mr
from app.services.notification_service import NotificationService
from app.services.outbound_alerts import EVENT_TYPES, event_type

ET = ZoneInfo("America/New_York")

CPI = {"kind": "cpi", "date": "2026-11-10", "start_date": "2026-11-10", "time_et": "08:30",
       "title": "IPC de EE. UU. (inflación)", "detail": None, "source": "BLS",
       "source_url": "https://www.bls.gov/schedule/news_release/", "label": "OFICIAL"}
FOMC = {"kind": "fomc", "date": "2026-12-09", "start_date": "2026-12-08", "time_et": None,
        "title": "Reunión del FOMC (decisión de tipos)", "detail": "Con proyecciones económicas",
        "source": "Reserva Federal", "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "label": "OFICIAL"}


def at(day: str, hh: int, mm: int = 0) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, hh, mm, tzinfo=ET).astimezone(UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="owner"))
        session.commit()
        session.info.update(tenant_id=1, user_id="owner")
        yield session
    engine.dispose()


def test_event_type_is_registered_and_mapped(db):
    assert "macro_event" in EVENT_TYPES
    row = ResearchAlert(tenant_id=1, alert_type="macro_event", title="t", message="m", fingerprint="x")
    assert event_type(db, row) == "macro_event"


def test_windows_with_published_time():
    start = at("2026-11-10", 8, 30)
    assert mr.due_windows(CPI, start - timedelta(hours=25)) == []
    assert mr.due_windows(CPI, start - timedelta(hours=24)) == ["24h"]
    assert mr.due_windows(CPI, start - timedelta(hours=1, minutes=1)) == ["24h"]
    assert mr.due_windows(CPI, start - timedelta(hours=1)) == ["1h"]
    assert mr.due_windows(CPI, start - timedelta(minutes=1)) == ["1h"]
    assert mr.due_windows(CPI, start) == []


def test_date_only_event_never_gets_a_one_hour_reminder():
    day = at("2026-12-09", 0)
    assert mr.due_windows(FOMC, day - timedelta(hours=25)) == []
    assert mr.due_windows(FOMC, day - timedelta(hours=23)) == ["day"]
    assert mr.due_windows(FOMC, day + timedelta(hours=10)) == ["day"]
    assert mr.due_windows(FOMC, day + timedelta(hours=25)) == []


@pytest.mark.parametrize("bad", [{"date": "nope"}, {}, {"date": "2026-11-10", "time_et": "xx:yy"}])
def test_malformed_events_are_ignored(bad):
    assert mr.due_windows(bad, datetime.now(UTC)) == []


def test_emit_is_idempotent_and_carries_source(db):
    now = at("2026-11-09", 12)
    first = mr.emit_macro_reminders(db, [CPI, FOMC], now)
    assert first["created"] == 1
    second = mr.emit_macro_reminders(db, [CPI, FOMC], now)
    assert second == {"created": 0, "existing": 1, "alert_ids": []}
    alert = db.scalar(select(ResearchAlert))
    assert alert.alert_type == "macro_event" and alert.channels == ["in_app"]
    assert "Fuente: BLS (OFICIAL)" in alert.message and "08:30 (hora de Nueva York)" in alert.message
    assert alert.title.endswith("en unas 20 h")
    assert alert.metadata_["window"] == "24h" and alert.metadata_["source"] == "BLS"


def test_one_hour_window_is_a_separate_alert(db):
    mr.emit_macro_reminders(db, [CPI], at("2026-11-09", 12))
    out = mr.emit_macro_reminders(db, [CPI], at("2026-11-10", 7, 45))
    assert out["created"] == 1
    titles = sorted(row.title for row in db.scalars(select(ResearchAlert)))
    assert any(t.endswith("en 45 min") for t in titles)
    assert mr.emit_macro_reminders(db, [CPI], at("2026-11-10", 8, 0))["existing"] == 1
    assert mr.emit_macro_reminders(db, [CPI], at("2026-11-10", 9))["created"] == 0


def test_exact_hour_text_and_date_only_wording(db):
    mr.emit_macro_reminders(db, [CPI], at("2026-11-10", 7, 30))
    mr.emit_macro_reminders(db, [FOMC], at("2026-12-08", 9))
    mr.emit_macro_reminders(db, [{**FOMC, "date": "2026-12-10", "kind": "fomc2"}], at("2026-12-10", 9))
    titles = [row.title for row in db.scalars(select(ResearchAlert)) if "FOMC" in row.title]
    assert any(t.endswith("mañana") for t in titles) and any(t.endswith("hoy") for t in titles)
    body = db.scalar(select(ResearchAlert.message).where(ResearchAlert.title.like("%mañana")))
    assert "hora no publicada por la fuente" in body and "Con proyecciones económicas." in body


def test_exactly_sixty_minutes_says_one_hour():
    event = {**CPI}
    start = at("2026-11-10", 8, 30)
    assert mr._when_text(event, "1h", start - timedelta(hours=1)) == "en 1 h"


def test_requires_tenant_and_skips_incomplete_events():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as bare:
        with pytest.raises(ValueError):
            mr.emit_macro_reminders(bare, [CPI])
        bare.info["tenant_id"] = 1
        assert mr.emit_macro_reminders(bare, [{"title": "sin clave"}], at("2026-11-09", 12))["created"] == 0


def test_race_on_fingerprint_counts_as_existing(db, monkeypatch):
    mr.emit_macro_reminders(db, [CPI], at("2026-11-09", 12))
    monkeypatch.setattr(db, "scalar", lambda *_a, **_k: None)  # simula la carrera
    out = mr.emit_macro_reminders(db, [CPI], at("2026-11-09", 12))
    assert out["created"] == 0 and out["existing"] == 1


def test_telegram_text_has_title_message_and_no_technical_ids():
    text = NotificationService._telegram_text({
        "type": "macro_event", "title": "IPC: mañana", "message": "Fuente: BLS (OFICIAL).",
        "severity": "medium", "company_id": None, "alert_id": 7,
    })
    assert text == "IPC: mañana\nFuente: BLS (OFICIAL)."
    assert "Alert id" not in text


def test_actor_emits_and_dispatches(db, monkeypatch):
    from app.services import macro_calendar_service
    from app.workers import dramatiq_app

    async def fake(start, end, **_k):
        return {"status": "ready", "events": [CPI], "sources": []}

    monkeypatch.setattr(macro_calendar_service, "get_macro_events", fake)
    monkeypatch.setattr(dramatiq_app, "_session", lambda *_a: db)
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: "lease")
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: None)
    monkeypatch.setattr(dramatiq_app, "_run", lambda coro: __import__("asyncio").run(coro))
    monkeypatch.setattr(mr, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: at("2026-11-09", 12)),
                                                    "strptime": staticmethod(datetime.strptime)}))
    closed = []
    monkeypatch.setattr(db, "close", lambda: closed.append(1))
    out = dramatiq_app.dispatch_macro_reminders.fn(1, "owner")
    assert out["status"] == "ok" and out["created"] == 1 and closed


def test_actor_skips_when_source_unavailable_or_lease_held(db, monkeypatch):
    from app.services import macro_calendar_service
    from app.workers import dramatiq_app

    async def down(start, end, **_k):
        return {"status": "unavailable", "events": [], "sources": []}

    monkeypatch.setattr(macro_calendar_service, "get_macro_events", down)
    monkeypatch.setattr(dramatiq_app, "_session", lambda *_a: db)
    monkeypatch.setattr(dramatiq_app, "release_job_lease", lambda *a, **k: None)
    monkeypatch.setattr(dramatiq_app, "_run", lambda coro: __import__("asyncio").run(coro))
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: "lease")
    assert dramatiq_app.dispatch_macro_reminders.fn(1, "owner")["reason"] == "source_unavailable"
    monkeypatch.setattr(dramatiq_app, "acquire_job_lease", lambda *a, **k: None)
    assert dramatiq_app.dispatch_macro_reminders.fn(1, "owner")["reason"] == "lease_held"
    assert db.scalar(select(ResearchAlert)) is None
