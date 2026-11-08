"""Guardas de cobertura compartidas de los canales outbound (alert_category /
alert_after_opt_in en outbound_alerts).

Telegram (subscription_for), push y correo (preference_for) abrían con la
misma guarda de tenant copiada y cerraban con la misma comparación "la alerta
nació tras el alta" con normalización de tz copiada. Se fija el contrato de
ambas y que los tres caminos las usan sin reintroducir su copia.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.models import ResearchAlert, Tenant
from app.models.entities import Base
from app.services.outbound_alerts import alert_after_opt_in, alert_category


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _alert(tenant_id, alert_type="macro_event") -> ResearchAlert:
    return ResearchAlert(
        tenant_id=tenant_id,
        company_id=None,
        severity="medium",
        status="open",
        alert_type=alert_type,
        title="t",
        message="m",
        fingerprint=f"fp-{tenant_id}-{alert_type}",
        channels=["in_app"],
        last_triggered_at=datetime(2026, 11, 9, tzinfo=UTC),
        metadata_={},
    )


def test_categoria_para_alerta_del_tenant(db):
    tenant = Tenant(external_id="cov-tenant", name="A")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id
    assert alert_category(db, _alert(tenant.id)) == "macro_event"


def test_categoria_rechaza_otro_tenant_y_tipo_desconocido(db):
    tenant = Tenant(external_id="cov-tenant", name="A")
    db.add(tenant)
    db.commit()
    db.info["tenant_id"] = tenant.id
    assert alert_category(db, _alert(tenant.id + 1)) is None
    assert alert_category(db, _alert(tenant.id, alert_type="otro_tipo")) is None
    assert alert_category(db, _alert(None)) is None


def test_tras_el_alta_normaliza_tz_en_ambos_lados():
    alta = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert alert_after_opt_in(datetime(2026, 11, 9, 13, 0), alta) is True
    assert alert_after_opt_in(datetime(2026, 11, 9, 12, 0, tzinfo=UTC), datetime(2026, 11, 9, 12, 0)) is True
    assert alert_after_opt_in(datetime(2026, 11, 9, 11, 0, tzinfo=UTC), alta) is False
    assert alert_after_opt_in(datetime(2026, 11, 9, 11, 0), datetime(2026, 11, 9, 12, 0)) is False


def test_los_tres_canales_usan_las_guardas_sin_copias():
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "app/services/outbound_alerts.py",
        "app/services/web_push.py",
        "app/services/email_alerts.py",
    ):
        src = (root / rel).read_text(encoding="utf-8")
        assert "alert_category(db, alert)" in src, rel
        assert "alert_after_opt_in(" in src, rel
    for rel in ("app/services/web_push.py", "app/services/email_alerts.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "tzinfo is None" not in src, rel
