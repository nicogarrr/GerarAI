"""Destinos globales de notificacion = del propietario (3 usuarios).

ALERT_EMAIL_TO (SMTP), los webhooks de email/push y el TELEGRAM_CHAT_ID de
aprobacion de tesis son UN destino para toda la instalacion. Antes, una alerta
del usuario 2 con canal "email" salia al correo del propietario (sus
posiciones a la vista de otro) y el usuario 2 no recibia nada. Ahora solo las
alertas del tenant propietario usan esos destinos.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, ResearchAlert, Tenant
from app.services import notification_service, owner_destination
from app.services import thesis_approval_service as approval
from app.services.notification_service import NotificationService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for ext in ("user-owner", "user-dos", "user-tres"):
            session.add(Tenant(external_id=ext, name=ext, metadata_={"created_by": ext}))
        session.commit()
        yield session


def _tenant(db, ext):
    return db.query(Tenant).filter(Tenant.external_id == ext).one().id


def _alert(db, tenant_id, n):
    company = Company(
        ticker=f"T{n}", name="Test", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    alert = ResearchAlert(
        tenant_id=tenant_id, company_id=company.id, alert_type="price_above",
        severity="high", title=f"T{n}: price_above", message="matched",
        fingerprint=f"fp-owner-{n}", channels=["in_app", "email", "push"], metadata_={},
    )
    db.add(alert)
    db.commit()
    return alert


class _Client:
    calls: list = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, json):
        type(self).calls.append((url, json))
        return SimpleNamespace(raise_for_status=lambda: None)


def _settings(**over):
    base = dict(
        telegram_enabled=False, telegram_bot_token=None, telegram_chat_id=None,
        telegram_api_base_url="https://api.telegram.org", telegram_timeout_seconds=10,
        alert_email_webhook_url="https://hooks.example/email",
        alert_push_webhook_url="https://hooks.example/push",
        global_alert_owner_user_id=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _dispatch(monkeypatch, db, tenant_id, n, settings):
    _Client.calls = []
    monkeypatch.setattr(notification_service.httpx, "Client", _Client)
    monkeypatch.setattr(notification_service, "get_settings", lambda: settings)
    return NotificationService().dispatch(db, _alert(db, tenant_id, n))


def test_owner_alert_still_uses_global_email_and_push(monkeypatch, db):
    deliveries = _dispatch(monkeypatch, db, _tenant(db, "user-owner"), 1, _settings())
    assert deliveries["email"]["status"] == "delivered"
    assert deliveries["push"]["status"] == "delivered"
    assert sorted(url for url, _ in _Client.calls) == [
        "https://hooks.example/email", "https://hooks.example/push",
    ]


@pytest.mark.parametrize("ext", ["user-dos", "user-tres"])
def test_other_users_alerts_never_reach_the_owner_destination(monkeypatch, db, ext):
    deliveries = _dispatch(monkeypatch, db, _tenant(db, ext), 2, _settings())
    assert _Client.calls == []
    assert deliveries["in_app"]["status"] == "delivered"
    for channel in ("email", "push"):
        assert deliveries[channel]["status"] == "not_configured"
        assert deliveries[channel]["error"] == owner_destination.NOT_OWNER_ERROR


def test_explicit_owner_setting_wins_over_first_account(monkeypatch, db):
    settings = _settings(global_alert_owner_user_id="user-tres")
    first = _dispatch(monkeypatch, db, _tenant(db, "user-owner"), 3, settings)
    assert _Client.calls == [] and first["email"]["status"] == "not_configured"
    third = _dispatch(monkeypatch, db, _tenant(db, "user-tres"), 4, settings)
    assert third["email"]["status"] == "delivered"


def test_no_tenant_keeps_single_user_behaviour(monkeypatch, db):
    deliveries = _dispatch(monkeypatch, db, None, 5, _settings())
    assert deliveries["email"]["status"] == "delivered"


def test_thesis_of_another_user_is_not_sent_to_owner_telegram(monkeypatch, db):
    _Client.calls = []
    monkeypatch.setattr(approval.httpx, "Client", _Client)
    settings = SimpleNamespace(
        telegram_enabled=True, telegram_approval_enabled=True,
        telegram_bot_token="test-token", telegram_chat_id="12345",
        telegram_api_base_url="https://api.telegram.org", telegram_timeout_seconds=10,
        global_alert_owner_user_id=None,
    )
    thesis = SimpleNamespace(
        id=99, tenant_id=_tenant(db, "user-dos"), version=1, status="final",
        executive_summary="Tesis privada del usuario dos",
    )
    result = approval.send_thesis_approval_request(db, thesis, "TDOS", settings)
    assert result == {"status": "not_configured", "error": owner_destination.NOT_OWNER_ERROR}
    assert _Client.calls == []
    assert owner_destination.may_use_global_destination(db, _tenant(db, "user-owner"), settings)
