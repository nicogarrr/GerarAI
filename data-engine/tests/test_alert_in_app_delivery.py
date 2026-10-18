"""Toda alerta in_app creada fuera de dispatch deja su fila de entrega."""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AlertDelivery, ResearchAlert
from app.services.notification_service import record_in_app_delivery
from tests.test_ibkr_import import _tenant_session


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = _tenant_session(engine)
    return db


def _alert(db, channels):
    a = ResearchAlert(
        severity="high", status="open", alert_type="t", title="x", message="m",
        fingerprint="fp-" + "-".join(channels), channels=channels, metadata_={},
    )
    db.add(a)
    db.flush()
    return a


def test_in_app_alert_gets_delivered_row_once():
    db = _db()
    a = _alert(db, ["in_app"])
    record_in_app_delivery(db, a)
    record_in_app_delivery(db, a)
    rows = db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == a.id)).all()
    assert [(r.channel, r.status) for r in rows] == [("in_app", "delivered")]
    db.close()


def test_non_in_app_alert_gets_no_row_and_nothing_is_sent():
    db = _db()
    a = _alert(db, ["email"])
    record_in_app_delivery(db, a)
    assert db.scalars(select(AlertDelivery)).all() == []
    db.close()


def test_creators_record_in_app_delivery():
    import pathlib

    for name in ("asts_spacex_signal", "filing_intelligence", "jev_availability", "review_alert_service"):
        src = pathlib.Path(f"app/services/{name}.py").read_text()
        assert "record_in_app_delivery(db, alert)" in src or "record_in_app_delivery(tenant_db, alert)" in src, name


def test_backfill_migration_is_safe_for_postgres():
    import importlib.util
    import pathlib

    path = pathlib.Path("alembic/versions/0059_alert_in_app_delivery.py")
    spec = importlib.util.spec_from_file_location("m0059", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # alembic_version.version_num es VARCHAR(32)
    assert len(mod.revision) <= 32 and path.stem == mod.revision
    # Un creador concurrente no debe abortar la migracion (UNIQUE alert_id+canal)
    assert "ON CONFLICT (alert_id, channel) DO NOTHING" in path.read_text()
