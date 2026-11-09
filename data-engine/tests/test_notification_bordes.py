"""Bordes de notification_service: carreras UNIQUE en entrega in_app y
_ensure_delivery_row, excepcion en dispatch que no frena otros canales,
reconciliador (filtro por tenant, alerta borrada, alerta rota), extraccion
de Retry-After, clasificacion 5xx y bordes de _telegram_text.

Fuera de alcance a proposito: la rama dca_level de _telegram_text (575-577),
adyacente a DCA (zona vetada).
"""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import AlertDelivery, Base, Company, ResearchAlert
from app.services import notification_service
from app.services.notification_service import NotificationService, record_in_app_delivery

OLD = datetime.now(UTC) - timedelta(seconds=notification_service.STALE_CLAIM_SECONDS + 60)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _alert(db: Session, channels: list[str], metadata: dict | None = None) -> ResearchAlert:
    company = Company(
        ticker="AAPL",
        name="Apple",
        exchange="NASDAQ",
        currency="USD",
        sector="Tech",
        industry="Tech",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    alert = ResearchAlert(
        company_id=company.id,
        alert_type="price_above",
        severity="high",
        title="AAPL: price_above > 200",
        message="AAPL rule matched: observed=210",
        fingerprint="fp-bordes-1",
        channels=channels,
        metadata_=metadata or {},
    )
    db.add(alert)
    db.commit()
    return alert


def _webhook_settings():
    return SimpleNamespace(
        telegram_enabled=False,
        telegram_bot_token=None,
        telegram_chat_id=None,
        telegram_api_base_url="https://api.telegram.org",
        telegram_timeout_seconds=10,
        alert_email_webhook_url="https://hooks.example/email",
        alert_push_webhook_url="https://hooks.example/push",
    )


def _status_error(status: int, headers: dict | None = None, json_body: dict | None = None):
    request = httpx.Request("POST", "https://api.telegram.org/botX/sendMessage")
    response = httpx.Response(status, headers=headers or {}, json=json_body, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_record_in_app_hace_flush_cuando_la_alerta_no_tiene_id(db):
    company = Company(
        ticker="MSFT",
        name="Microsoft",
        exchange="NASDAQ",
        currency="USD",
        sector="Tech",
        industry="Tech",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    alert = ResearchAlert(
        company_id=company.id,
        alert_type="price_above",
        severity="low",
        title="t",
        message="m",
        fingerprint="fp-bordes-2",
        channels=["in_app"],
        metadata_={},
    )
    db.add(alert)
    assert alert.id is None
    record_in_app_delivery(db, alert)
    assert alert.id is not None
    db.commit()
    row = db.query(AlertDelivery).filter_by(alert_id=alert.id, channel="in_app").one()
    assert row.status == "delivered"


def test_record_in_app_traga_integrity_error_de_carrera(monkeypatch, db):
    alert = _alert(db, ["in_app"])
    db.refresh(alert)  # atributos cargados: ningun acceso dispara query+autoflush extra
    calls = {"n": 0}
    real_flush = Session.flush

    def flush_cascado_en_el_insert(self):
        calls["n"] += 1
        if calls["n"] >= 2:  # el primero es el autoflush del exists-check
            raise IntegrityError("INSERT INTO alert_deliveries", {}, Exception("uq_alert_channel"))
        return real_flush(self)

    monkeypatch.setattr(Session, "flush", flush_cascado_en_el_insert)
    record_in_app_delivery(db, alert)  # no debe propagar
    assert calls["n"] >= 2
    monkeypatch.undo()
    db.rollback()


def test_dispatch_excepcion_en_un_canal_no_frena_los_demas(monkeypatch, db):
    alert = _alert(db, ["push", "in_app"])
    monkeypatch.setattr(notification_service, "get_settings", _webhook_settings)

    def webhook_roto(self, settings, payload, channel):
        raise RuntimeError("boom")

    monkeypatch.setattr(NotificationService, "_dispatch_webhook", webhook_roto)
    deliveries = NotificationService().dispatch(db, alert)
    assert deliveries["push"]["status"] == "failed"
    assert deliveries["push"]["error"] == "dispatch_error"
    assert deliveries["in_app"]["status"] == "delivered"


def test_reconcile_filtra_por_tenant(db):
    alert = _alert(db, ["push"])
    db.add(
        AlertDelivery(
            tenant_id=alert.tenant_id,
            alert_id=alert.id,
            channel="push",
            status="sending",
            attempts=1,
            updated_at=OLD,
        )
    )
    db.commit()
    # Fila de OTRO tenant via Core: el guard ORM cross-tenant (a proposito)
    # bloquea session.add con tenant ajeno, y aqui la fila ajena es el dato.
    db.connection().execute(
        AlertDelivery.__table__.insert().values(
            tenant_id=999999,
            alert_id=alert.id,
            channel="email",
            status="sending",
            attempts=1,
            created_at=OLD,
            updated_at=OLD,
        )
    )
    db.commit()
    result = NotificationService().reconcile_stale_deliveries(db, tenant_id=alert.tenant_id)
    assert result["candidates"] == 1
    assert result["errors"] == []


def test_reconcile_alerta_borrada_la_salta_sin_error(db):
    alert = _alert(db, ["push"])
    db.add(
        AlertDelivery(
            tenant_id=alert.tenant_id,
            alert_id=424242,
            channel="push",
            status="sending",
            attempts=1,
            updated_at=OLD,
        )
    )
    db.commit()
    result = NotificationService().reconcile_stale_deliveries(db)
    assert result["candidates"] == 1
    assert result["redispatched"] == 0
    assert result["errors"] == []


def test_reconcile_alerta_rota_anota_el_error_y_sigue(monkeypatch, db):
    alert = _alert(db, ["push"])
    db.add(
        AlertDelivery(
            tenant_id=alert.tenant_id,
            alert_id=alert.id,
            channel="push",
            status="sending",
            attempts=1,
            updated_at=OLD,
        )
    )
    db.commit()

    def dispatch_roto(self, db_, alert_):
        raise RuntimeError("alerta rota")

    monkeypatch.setattr(NotificationService, "dispatch", dispatch_roto)
    result = NotificationService().reconcile_stale_deliveries(db)
    assert result["candidates"] == 1
    assert result["redispatched"] == 0
    assert result["errors"] == [f"alert_id={alert.id}"]


def test_retry_after_json_sin_valor_devuelve_none():
    exc = _status_error(429, json_body={"parameters": {}})
    assert NotificationService._extract_retry_after(exc) is None


def test_retry_after_fecha_http_naive_se_asume_utc():
    future = datetime.now(UTC) + timedelta(minutes=30)
    exc = _status_error(429, headers={"Retry-After": format_datetime(future.replace(tzinfo=None))})
    seconds = NotificationService._extract_retry_after(exc)
    assert isinstance(seconds, int)
    assert 0 < seconds <= 1800


def test_retry_after_fecha_http_con_zona():
    future = datetime.now(UTC) + timedelta(minutes=30)
    exc = _status_error(429, headers={"Retry-After": format_datetime(future, usegmt=True)})
    seconds = NotificationService._extract_retry_after(exc)
    assert isinstance(seconds, int)
    assert 0 < seconds <= 1800


def test_retry_after_fecha_invalida_devuelve_none():
    exc = _status_error(429, headers={"Retry-After": "no-es-fecha-ni-numero"})
    assert NotificationService._extract_retry_after(exc) is None


def test_retry_after_en_el_pasado_devuelve_none():
    exc = _status_error(429, headers={"Retry-After": "Mon, 09 Nov 2020 00:00:01 GMT"})
    assert NotificationService._extract_retry_after(exc) is None


def test_clasifica_5xx_como_unknown():
    assert NotificationService._classify_send_error(_status_error(500)) == "unknown"


def test_ensure_delivery_row_traga_integrity_error_de_carrera(monkeypatch, db):
    alert = _alert(db, ["push"])

    def commit_cascado(self):
        raise IntegrityError("INSERT INTO alert_deliveries", {}, Exception("uq_alert_channel"))

    monkeypatch.setattr(Session, "commit", commit_cascado)
    NotificationService()._ensure_delivery_row(db, alert, "push")  # no debe propagar
    monkeypatch.undo()
    db.commit()  # tras el rollback interno de la carrera no queda nada pendiente
    assert db.query(AlertDelivery).filter_by(alert_id=alert.id, channel="push").count() == 0


def test_telegram_text_fecha_no_datetime_no_lleva_sufijo():
    text = NotificationService._telegram_text(
        {
            "company_name": "Apple",
            "source_headline": "Apple presenta un 10-K",
            "type": "tracked_news",
            "event_date": "ayer",
        }
    )
    assert "10-K" in text
    assert "detectada" not in text


def test_telegram_text_url_malformada_no_se_abre_y_sin_ticker_no_hay_enlace():
    text = NotificationService._telegram_text(
        {
            "company_name": "Apple",
            "source_headline": "Apple presenta un 10-K",
            "type": "tracked_news",
            "event_date": None,
            "source_url": "http://[malformada",
        }
    )
    assert "Abrir documento" not in text
    assert "tesis afectada" not in text


def test_telegram_text_confianza_jev_no_numerica_cae_a_cero():
    text = NotificationService._telegram_text(
        {
            "severity": "high",
            "title": "Alerta",
            "message": "Mensaje",
            "company_id": 1,
            "alert_id": 2,
            "jev_urgency": {"label": "alta", "confidence": "abc"},
        }
    )
    assert "Jev urgency: alta (conf 0.00)" in text
