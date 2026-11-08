"""Primitiva compartida de dedup de ResearchAlert (insert_alert_once).

in_app_alerts.persist_in_app_alerts y macro_reminders.emit_macro_reminders
llevaban la misma inserción idempotente copiada (select previo por
(tenant, fingerprint) + savepoint con IntegrityError). Fija el contrato de
la primitiva y que ambos callers la usan sin reintroducir su copia.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services.in_app_alerts import insert_alert_once

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _tenant(db: Session) -> Tenant:
    tenant = Tenant(external_id="once-tenant", name="A")
    db.add(tenant)
    db.commit()
    return tenant


def _alert(tenant_id, fingerprint: str) -> ResearchAlert:
    return ResearchAlert(
        tenant_id=tenant_id,
        company_id=None,
        severity="medium",
        status="open",
        alert_type="macro_event",
        title="titulo",
        message="mensaje",
        fingerprint=fingerprint,
        channels=["in_app"],
        last_triggered_at=NOW,
        metadata_={},
    )


def test_inserta_cuando_no_existe(db):
    tenant = _tenant(db)
    assert insert_alert_once(db, _alert(tenant.id, "fp-nueva")) is True
    db.commit()
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_no_duplica_mismo_tenant_y_fingerprint(db):
    tenant = _tenant(db)
    assert insert_alert_once(db, _alert(tenant.id, "fp-dup")) is True
    assert insert_alert_once(db, _alert(tenant.id, "fp-dup")) is False
    db.commit()
    rows = db.scalars(select(ResearchAlert)).all()
    assert len(rows) == 1


def test_mismo_fingerprint_en_otro_tenant_si_inserta(db):
    tenant = _tenant(db)
    otro = Tenant(external_id="once-tenant-b", name="B")
    db.add(otro)
    db.commit()
    assert insert_alert_once(db, _alert(tenant.id, "fp-x")) is True
    assert insert_alert_once(db, _alert(otro.id, "fp-x")) is True
    db.commit()
    assert len(db.scalars(select(ResearchAlert)).all()) == 2


def test_callers_usan_la_primitiva_sin_copias():
    root = Path(__file__).resolve().parents[1]
    macro = (root / "app" / "services" / "macro_reminders.py").read_text(encoding="utf-8")
    in_app = (root / "app" / "services" / "in_app_alerts.py").read_text(encoding="utf-8")
    assert "insert_alert_once(db, alert)" in macro
    assert "begin_nested" not in macro
    assert "insert_alert_once(db, alert)" in in_app
