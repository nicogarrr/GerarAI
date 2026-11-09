"""Persistencia idempotente de alertas in-app (app/services/in_app_alerts.py).

Hueco de cobertura: el modulo no tenia tests propios (los watchdogs que lo
usan tienen los suyos, de dominio). Se fija el contrato de dedup por
fingerprint: cada alerta se inserta una sola vez por (tenant, fingerprint),
las repetidas cuentan como existentes y la funcion devuelve
(ids_creados, ya_existentes) con un unico commit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services.in_app_alerts import InAppAlert, persist_in_app_alerts

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _tenant(db: Session) -> Tenant:
    tenant = Tenant(external_id="alerts-tenant", name="A")
    db.add(tenant)
    db.commit()
    return tenant


def _alert(fingerprint: str, **kwargs) -> InAppAlert:
    return InAppAlert(
        fingerprint=fingerprint,
        alert_type=kwargs.get("alert_type", "queue_watchdog"),
        severity=kwargs.get("severity", "warning"),
        title=kwargs.get("title", f"titulo {fingerprint}"),
        message=kwargs.get("message", "mensaje"),
        metadata=kwargs.get("metadata", {"k": "v"}),
    )


def test_creates_each_alert_once(db):
    tenant = _tenant(db)
    created, existing = persist_in_app_alerts(
        db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp1"), _alert("fp2")]
    )
    assert existing == 0
    assert len(created) == 2
    rows = db.scalars(select(ResearchAlert)).all()
    assert len(rows) == 2
    row = next(r for r in rows if r.fingerprint == "fp1")
    assert row.tenant_id == tenant.id
    assert row.status == "open"
    assert row.channels == ["in_app"]
    assert row.last_triggered_at is not None
    assert row.metadata_ == {"k": "v"}


def test_repeat_call_dedups_by_fingerprint(db):
    tenant = _tenant(db)
    first, _ = persist_in_app_alerts(db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp1")])
    second, existing = persist_in_app_alerts(
        db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp1"), _alert("fp3")]
    )
    assert len(first) == 1
    assert len(second) == 1  # solo fp3 es nueva
    assert existing == 1  # fp1 ya existia
    assert db.scalars(select(ResearchAlert)).all().__len__() == 2


def test_same_fingerprint_twice_in_one_batch_counts_existing(db):
    tenant = _tenant(db)
    created, existing = persist_in_app_alerts(
        db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp1"), _alert("fp1")]
    )
    assert len(created) == 1
    assert existing == 1
    assert len(db.scalars(select(ResearchAlert)).all()) == 1


def test_same_fingerprint_other_tenant_is_a_distinct_alert(db):
    tenant_a = _tenant(db)
    tenant_b = Tenant(external_id="alerts-tenant-b", name="B")
    db.add(tenant_b)
    db.commit()
    created_a, _ = persist_in_app_alerts(db, tenant_id=tenant_a.id, now=NOW, alerts=[_alert("fp1")])
    created_b, existing_b = persist_in_app_alerts(
        db, tenant_id=tenant_b.id, now=NOW, alerts=[_alert("fp1")]
    )
    assert len(created_a) == 1 and len(created_b) == 1
    assert existing_b == 0  # el fingerprint es por tenant
    assert len(db.scalars(select(ResearchAlert)).all()) == 2


def test_nueva_alerta_graba_su_entrega_in_app(db):
    # Sin la fila de entrega, la UI muestra "sin registro de entrega" para
    # siempre (prod, 09-nov-2026: "Cola yahoo atascada ... sin registro").
    from app.models import AlertDelivery

    tenant = _tenant(db)
    created, _ = persist_in_app_alerts(
        db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp1"), _alert("fp2")]
    )
    deliveries = db.scalars(select(AlertDelivery)).all()
    assert len(deliveries) == 2
    assert {d.alert_id for d in deliveries} == set(created)
    for d in deliveries:
        assert d.channel == "in_app"
        assert d.status == "delivered"
        assert d.attempts == 1


def test_dedup_no_duplica_la_fila_de_entrega(db):
    from app.models import AlertDelivery

    tenant = _tenant(db)
    persist_in_app_alerts(db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp1")])
    persist_in_app_alerts(db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp1")])
    assert len(db.scalars(select(AlertDelivery)).all()) == 1


def test_insert_alert_once_registra_entrega_en_la_primitiva(db):
    # La primitiva compartida (macro_reminders, watchdogs) tambien registra.
    from app.models import AlertDelivery
    from app.services.in_app_alerts import insert_alert_once

    tenant = _tenant(db)
    alert = ResearchAlert(
        tenant_id=tenant.id, company_id=None, severity="medium", status="open",
        alert_type="macro_reminder", title="t", message="m", fingerprint="fp-x",
        channels=["in_app"], last_triggered_at=NOW, metadata_={},
    )
    assert insert_alert_once(db, alert) is True
    deliveries = db.scalars(select(AlertDelivery)).all()
    assert len(deliveries) == 1
    assert deliveries[0].channel == "in_app"
    assert insert_alert_once(db, alert) is False  # dedup: sin segunda entrega
    assert len(db.scalars(select(AlertDelivery)).all()) == 1


def test_dedup_backfilla_la_entrega_de_alerta_pre_fix(db):
    # Alerta persistida ANTES del fix (sin fila de entrega, como las "Cola X
    # atascada" del 09-nov-2026 en prod): el reencuentro por dedup la cura.
    from app.models import AlertDelivery

    tenant = _tenant(db)
    legacy = ResearchAlert(
        tenant_id=tenant.id, company_id=None, severity="high", status="open",
        alert_type="queue_stuck", title="Cola yahoo atascada", message="m",
        fingerprint="fp-legacy", channels=["in_app"], last_triggered_at=NOW, metadata_={},
    )
    db.add(legacy)
    db.commit()
    assert db.scalars(select(AlertDelivery)).all() == []

    created, existing = persist_in_app_alerts(
        db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp-legacy")]
    )
    assert created == []
    assert existing == 1
    deliveries = db.scalars(select(AlertDelivery)).all()
    assert len(deliveries) == 1
    assert deliveries[0].alert_id == legacy.id
    assert deliveries[0].channel == "in_app"
    assert deliveries[0].status == "delivered"
    assert deliveries[0].attempts == 1

    # Idempotente: otro tick no duplica la entrega.
    persist_in_app_alerts(db, tenant_id=tenant.id, now=NOW, alerts=[_alert("fp-legacy")])
    assert len(db.scalars(select(AlertDelivery)).all()) == 1


def test_dedup_no_toca_alertas_ajenas_al_fingerprint(db):
    # El backfill es por (tenant, fingerprint): una alerta de otro tenant con
    # el mismo fingerprint no recibe entrega.
    from app.models import AlertDelivery

    tenant_a = _tenant(db)
    tenant_b = Tenant(external_id="alerts-tenant-b2", name="B2")
    db.add(tenant_b)
    db.commit()
    legacy_b = ResearchAlert(
        tenant_id=tenant_b.id, company_id=None, severity="high", status="open",
        alert_type="queue_stuck", title="t", message="m", fingerprint="fp-x",
        channels=["in_app"], last_triggered_at=NOW, metadata_={},
    )
    db.add(legacy_b)
    db.commit()
    persist_in_app_alerts(db, tenant_id=tenant_a.id, now=NOW, alerts=[_alert("fp-x")])
    deliveries_b = db.scalars(
        select(AlertDelivery).where(AlertDelivery.alert_id == legacy_b.id)
    ).all()
    assert deliveries_b == []
