"""Contrato canales declarados vs entrega (notification_service.dispatch).

Un canal sin handler explícito (in_app/telegram/push/email) NO rompe la
pasada ni se pierde en silencio: cae al webhook catch-all y queda su fila
de entrega con el motivo. Si mañana entra un canal nuevo (sms, slack) sin
handler, este contrato es el que garantiza que la alerta no desaparece.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AlertDelivery, Company, ResearchAlert
from app.services import notification_service
from app.services.notification_service import NotificationService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _alert(db, channels):
    company = Company(
        ticker="TST", name="Test", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    alert = ResearchAlert(
        tenant_id=None, company_id=company.id, alert_type="price_above",
        severity="high", title="TST: price_above", message="matched",
        fingerprint="fp-canal-" + "-".join(channels), channels=channels, metadata_={},
    )
    db.add(alert)
    db.commit()
    return alert


def _client_que_registra(calls: list):
    """Client httpx de mentira, uno por test: la lista de llamadas vive en el
    test, no en un atributo de clase que se reasignaba sin restaurar y fugaba
    estado entre tests (salvedad del auditor de #5007)."""

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, json):
            calls.append((url, json))
            return SimpleNamespace(raise_for_status=lambda: None)

    return Client


def _settings(**over):
    base = dict(
        telegram_enabled=False, telegram_bot_token=None, telegram_chat_id=None,
        telegram_api_base_url="https://api.telegram.org", telegram_timeout_seconds=10,
        alert_email_webhook_url=None, alert_push_webhook_url=None,
        global_alert_owner_user_id=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_canal_desconocido_cae_a_webhook_y_deja_fila_sin_romper_la_pasada(monkeypatch, db):
    alert = _alert(db, ["in_app", "pichon"])
    calls: list = []
    monkeypatch.setattr(notification_service.httpx, "Client", _client_que_registra(calls))
    monkeypatch.setattr(notification_service, "get_settings", lambda: _settings())

    deliveries = NotificationService().dispatch(db, alert)

    # El canal conocido se entrega con normalidad en la misma pasada.
    assert deliveries["in_app"]["status"] == "delivered"
    # El desconocido: catch-all webhook, sin endpoint -> not_configured, con fila.
    assert deliveries["pichon"]["status"] == "not_configured"
    assert "pichon" in (deliveries["pichon"]["error"] or "")
    assert calls == []  # sin endpoint no hay llamada de red
    rows = db.scalars(
        select(AlertDelivery).where(AlertDelivery.alert_id == alert.id)
    ).all()
    assert {(r.channel, r.status) for r in rows} == {
        ("in_app", "delivered"), ("pichon", "not_configured"),
    }


def test_canal_desconocido_con_webhook_generico_no_aplica_solo_email_push(monkeypatch, db):
    """El catch-all solo tiene endpoint para email/push; un canal nuevo aunque
    haya webhooks de email/push configurados NO se cuela por ellos."""
    alert = _alert(db, ["pichon"])
    calls = []
    monkeypatch.setattr(notification_service.httpx, "Client", _client_que_registra(calls))
    monkeypatch.setattr(
        notification_service, "get_settings",
        lambda: _settings(
            alert_email_webhook_url="https://hooks.example/email",
            alert_push_webhook_url="https://hooks.example/push",
        ),
    )

    deliveries = NotificationService().dispatch(db, alert)

    assert deliveries["pichon"]["status"] == "not_configured"
    assert calls == []
