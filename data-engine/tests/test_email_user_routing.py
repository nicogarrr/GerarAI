"""Avisos por correo al email de CADA usuario, no a la lista global.

ALERT_EMAIL_TO es un buzon unico de la instalacion (el del propietario). Con
varios usuarios, las alertas por correo tienen que salir a la direccion que el
frontend firma para CADA usuario (la de su sesion), solo con su opt-in por
tipo y nunca cruzadas: el correo de un usuario jamas va a otro ni a la lista
global cuando el usuario ya decidio (opt-out o alerta anterior al alta).
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.alerts import (
    EmailPreferenceIn,
    list_email_preferences,
    set_email_preference,
)
from app.core.auth import sign_email_identity, verified_email_identity
from app.models.entities import (
    Base,
    Company,
    EmailPreference,
    ResearchAlert,
    Tenant,
    UserEmailBinding,
)
from app.services import email_alerts, notification_service
from app.services.email_delivery import EmailContent, send_email
from app.services.notification_service import NotificationService

SECRET = "x" * 32
NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for ext in ("user-a", "user-b"):
            session.add(Tenant(external_id=ext, name=ext, metadata_={"created_by": ext}))
        session.commit()
        session.info.update(tenant_id=1, user_id="user-a")
        yield session
    engine.dispose()


def _settings(**over):
    base = dict(
        telegram_enabled=False, telegram_bot_token=None, telegram_chat_id=None,
        telegram_api_base_url="https://api.telegram.org", telegram_timeout_seconds=10,
        alert_email_to="buzon-global@example.com",
        alert_email_webhook_url=None, alert_push_webhook_url=None,
        global_alert_owner_user_id=None,
        smtp_host="smtp.example.com", smtp_port=587, smtp_from="avisos@gerarai.app",
        smtp_timeout_seconds=10, smtp_ssl=False, smtp_starttls=True,
        smtp_username="u", smtp_password="p",
    )
    base.update(over)
    return SimpleNamespace(**base)


class _FakeSmtp:
    calls: list = []


def _fake_send(settings, content, *, to=None, **_kwargs):
    _FakeSmtp.calls.append({"to": to, "subject": content.subject})
    return {"status": "delivered", "error": None}


def _alert(db, tenant_id, n, *, alert_type="earnings_reminder", channels=None, created_at=None):
    company = Company(
        ticker=f"T{n}", name="Test", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    alert = ResearchAlert(
        tenant_id=tenant_id, company_id=company.id, alert_type=alert_type,
        severity="high", title=f"T{n}: aviso", message="matched",
        fingerprint=f"fp-email-{n}", channels=channels or ["in_app"], metadata_={},
    )
    db.add(alert)
    db.commit()
    if created_at is not None:
        alert.created_at = created_at
        db.commit()
    return alert


def _bind(db, tenant=1, user="user-a", address="propio@example.com"):
    return email_alerts.sync_binding(db, tenant, user, address)


def _pref(db, tenant=1, user="user-a", event_type="earnings", enabled=True, enabled_at=None):
    row = EmailPreference(
        tenant_id=tenant, user_id=user, event_type=event_type, enabled=enabled,
        enabled_at=enabled_at or NOW,
    )
    db.add(row)
    db.commit()
    return row


def _dispatch(monkeypatch, db, alert, settings=None):
    _FakeSmtp.calls = []
    monkeypatch.setattr(notification_service, "send_email", _fake_send)
    monkeypatch.setattr(
        notification_service, "get_settings", lambda: settings or _settings()
    )
    return NotificationService().dispatch(db, alert)


def test_con_optin_sale_al_correo_propio_no_al_global(monkeypatch, db):
    _bind(db)
    _pref(db, enabled_at=NOW - timedelta(hours=1))
    deliveries = _dispatch(monkeypatch, db, _alert(db, 1, 1))
    assert deliveries["email"]["status"] == "delivered"
    assert _FakeSmtp.calls[0]["to"] == ["propio@example.com"]
    assert _FakeSmtp.calls[0]["to"] != ["buzon-global@example.com"]


def test_canal_email_se_anade_solo_con_optin(monkeypatch, db):
    _bind(db)
    _pref(db, enabled_at=NOW - timedelta(hours=1))
    alert = _alert(db, 1, 2, channels=["in_app"])
    assert "email" not in alert.channels
    deliveries = _dispatch(monkeypatch, db, alert)
    assert "email" in alert.channels
    assert deliveries["email"]["status"] == "delivered"


def test_otro_usuario_no_recibe_con_el_binding_ajeno(monkeypatch, db):
    # user-a tiene direccion y opt-in; la alerta es del tenant de user-b y la
    # sesion es de user-b: nada de user-a puede aplicar.
    _bind(db)
    _pref(db, enabled_at=NOW - timedelta(hours=1))
    db.info.update(tenant_id=2, user_id="user-b")
    alert = _alert(db, 2, 3, channels=["in_app", "email"])
    deliveries = _dispatch(monkeypatch, db, alert)
    assert _FakeSmtp.calls == []
    assert deliveries["email"]["status"] == "not_configured"


def test_optout_explicito_no_cae_a_la_lista_global(monkeypatch, db):
    _bind(db)
    _pref(db, enabled=False)
    # tenant 1 es el propietario (primera cuenta): sin la guarda, el correo
    # saldria a ALERT_EMAIL_TO ignorando el opt-out.
    deliveries = _dispatch(monkeypatch, db, _alert(db, 1, 4, channels=["in_app", "email"]))
    assert _FakeSmtp.calls == []
    assert deliveries["email"]["status"] == "skipped"


def test_alerta_anterior_al_alta_no_se_envia(monkeypatch, db):
    _bind(db)
    _pref(db, enabled_at=NOW)
    old_alert = _alert(db, 1, 5, channels=["in_app", "email"],
                       created_at=NOW - timedelta(days=1))
    deliveries = _dispatch(monkeypatch, db, old_alert)
    assert _FakeSmtp.calls == []
    assert deliveries["email"]["status"] == "skipped"


def test_sin_decision_previa_propietario_mantiene_destino_global(monkeypatch, db):
    # Sin binding ni preferencia (instalacion de un solo usuario) no cambia
    # nada: la cuenta propietaria sigue usando ALERT_EMAIL_TO.
    deliveries = _dispatch(monkeypatch, db, _alert(db, 1, 6, channels=["in_app", "email"]))
    assert _FakeSmtp.calls[0]["to"] is None  # send_email usa ALERT_EMAIL_TO
    assert deliveries["email"]["status"] == "delivered"


def test_optin_sin_binding_no_envia(monkeypatch, db):
    # Opt-in sin direccion firmada todavia: la alerta no puede salir.
    _pref(db, enabled_at=NOW - timedelta(hours=1))
    db.info.update(tenant_id=2, user_id="user-b")
    db2_alert = _alert(db, 2, 7, channels=["in_app", "email"])
    deliveries = _dispatch(monkeypatch, db, db2_alert)
    assert _FakeSmtp.calls == []
    assert deliveries["email"]["status"] == "not_configured"


# --- send_email con destinatario propio -------------------------------------


class _RecordingSmtp:
    messages: list = []

    def __init__(self, *args, **kwargs):
        pass

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, *_args):
        pass

    def send_message(self, message):
        type(self).messages.append(message)
        return {}

    def quit(self):
        pass


def test_send_email_con_to_ignora_la_lista_global():
    _RecordingSmtp.messages = []
    settings = _settings()
    result = send_email(
        settings,
        EmailContent(subject="s", text="t"),
        to=["propio@example.com"],
        smtp_factory=_RecordingSmtp,
    )
    assert result["status"] == "delivered"
    assert _RecordingSmtp.messages[0]["To"] == "propio@example.com"


def test_send_email_por_usuario_sin_alert_email_to():
    # Basta host+remitente: no hace falta la lista global para el correo propio.
    _RecordingSmtp.messages = []
    settings = _settings(alert_email_to="")
    result = send_email(
        settings,
        EmailContent(subject="s", text="t"),
        to=["propio@example.com"],
        smtp_factory=_RecordingSmtp,
    )
    assert result["status"] == "delivered"
    assert _RecordingSmtp.messages[0]["To"] == "propio@example.com"


def test_send_email_to_vacio_es_not_configured():
    settings = _settings()
    result = send_email(settings, EmailContent(subject="s", text="t"), to=[], smtp_factory=_RecordingSmtp)
    assert result["status"] == "not_configured"


# --- Binding solo con direccion firmada --------------------------------------


def test_sync_binding_crea_y_actualiza_sin_duplicar(db):
    row = _bind(db, address="uno@example.com")
    db.commit()
    same = _bind(db, address="uno@example.com")
    assert same.id == row.id
    updated = _bind(db, address="dos@example.com")
    db.commit()
    assert updated.id == row.id and updated.address == "dos@example.com"
    assert db.query(UserEmailBinding).count() == 1


def _firma(email, nonce="n" * 16, ts="1730000000"):
    return sign_email_identity(
        SECRET, tenant_id="user-a", user_id="user-a", timestamp=ts, nonce=nonce, email=email
    )


def test_email_firmado_se_acepta():
    email = "Propio@Example.com"
    assert verified_email_identity(
        SECRET, tenant_id="user-a", user_id="user-a", timestamp="1730000000",
        nonce="n" * 16, email_header=email, signature=_firma("propio@example.com"),
    ) == "propio@example.com"


def test_email_con_firma_ajena_se_descarta():
    firma_de_otro = sign_email_identity(
        SECRET, tenant_id="user-b", user_id="user-b", timestamp="1730000000",
        nonce="n" * 16, email="propio@example.com",
    )
    assert verified_email_identity(
        SECRET, tenant_id="user-a", user_id="user-a", timestamp="1730000000",
        nonce="n" * 16, email_header="propio@example.com", signature=firma_de_otro,
    ) is None


def test_email_sin_nonce_o_sin_firma_se_descarta():
    assert verified_email_identity(
        SECRET, tenant_id="user-a", user_id="user-a", timestamp="1",
        nonce=None, email_header="a@b.com", signature=_firma("a@b.com"),
    ) is None
    assert verified_email_identity(
        SECRET, tenant_id="user-a", user_id="user-a", timestamp="1",
        nonce="n" * 16, email_header="a@b.com", signature=None,
    ) is None


def test_email_malformado_o_firma_no_hex_se_descarta():
    assert verified_email_identity(
        SECRET, tenant_id="user-a", user_id="user-a", timestamp="1",
        nonce="n" * 16, email_header="no-es-email", signature=_firma("no-es-email"),
    ) is None
    assert verified_email_identity(
        SECRET, tenant_id="user-a", user_id="user-a", timestamp="1",
        nonce="n" * 16, email_header="a@b.com", signature="zz",
    ) is None


# --- API de preferencias ------------------------------------------------------


def test_api_lista_estado_por_defecto(db):
    from fastapi import HTTPException

    db.info.pop("user_id")
    with pytest.raises(HTTPException) as exc:
        list_email_preferences(db)
    assert exc.value.status_code == 401
    db.info.update(user_id="user-a")
    status = list_email_preferences(db)
    assert [row["event_type"] for row in status["preferences"]] == [
        "thesis_broken", "new_filing", "insiders", "shorts_rising", "daily_digest",
        "dca_levels", "macro_event", "earnings",
    ]
    assert all(row["enabled"] is False for row in status["preferences"])
    assert status["email"] is None


def test_api_activar_sin_binding_es_403(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        set_email_preference("earnings", EmailPreferenceIn(enabled=True), db)
    assert exc.value.status_code == 403


def test_api_activar_con_binding_y_apagar(db):
    _bind(db)
    out = set_email_preference("earnings", EmailPreferenceIn(enabled=True), db)
    assert out == {"event_type": "earnings", "enabled": True}
    first = db.query(EmailPreference).one()
    assert first.enabled_at is not None
    # Apagar y reactivar mueve enabled_at solo al reactivar.
    out = set_email_preference("earnings", EmailPreferenceIn(enabled=False), db)
    assert out["enabled"] is False
    out = set_email_preference("earnings", EmailPreferenceIn(enabled=True), db)
    assert out["enabled"] is True
    status = list_email_preferences(db)
    assert status["email"] == "propio@example.com"
    row = next(r for r in status["preferences"] if r["event_type"] == "earnings")
    assert row["enabled"] is True
