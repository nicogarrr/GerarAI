"""Canal email por SMTP: envio, clasificacion de errores y respaldo al webhook."""

import smtplib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import AlertDelivery, Base, ResearchAlert
from app.services import email_delivery
from app.services.email_delivery import EmailContent, recipients, send_email, smtp_configured
from app.services.notification_service import NotificationService


def _settings(**overrides):
    base = {
        "smtp_host": "smtp.example.test",
        "smtp_port": 587,
        "smtp_username": "nico@example.test",
        "smtp_password": "secreto-de-aplicacion",
        "smtp_from": "GerarAI <nico@example.test>",
        "smtp_starttls": True,
        "smtp_ssl": False,
        "smtp_timeout_seconds": 5.0,
        "alert_email_to": "nico@example.test, otro@example.test;nico@example.test",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_at: str | None = None
    exc: BaseException | None = None
    refused: dict = {}

    def __init__(self, host, port, timeout=None, **kwargs):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent = None
        FakeSMTP.instances.append(self)
        self._maybe_fail("connect")

    def _maybe_fail(self, step):
        self.calls.append(step)
        if FakeSMTP.fail_at == step and FakeSMTP.exc is not None:
            raise FakeSMTP.exc

    def ehlo(self):
        self._maybe_fail("ehlo")

    def starttls(self, context=None):
        self._maybe_fail("starttls")

    def login(self, user, password):
        self.login_args = (user, password)
        self._maybe_fail("login")

    def send_message(self, message):
        self._maybe_fail("send")
        self.sent = message
        return dict(FakeSMTP.refused)

    def quit(self):
        self.calls.append("quit")

    def close(self):
        self.calls.append("close")


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeSMTP.instances = []
    FakeSMTP.fail_at = None
    FakeSMTP.exc = None
    FakeSMTP.refused = {}
    yield


def _content():
    return EmailContent(subject="UBER entró en 4X DCA", text="texto", html="<p>html</p>")


def test_recipients_dedup_and_configured():
    settings = _settings()
    assert recipients(settings) == ["nico@example.test", "otro@example.test"]
    assert smtp_configured(settings)
    assert not smtp_configured(_settings(smtp_host=None))
    assert not smtp_configured(_settings(alert_email_to=" , "))
    assert send_email(_settings(smtp_from=None), _content())["status"] == "not_configured"


def test_send_success_multipart_with_starttls_and_login():
    result = send_email(_settings(), _content(), smtp_factory=FakeSMTP)
    assert result == {"status": "delivered", "error": None}
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.test", 587, 5.0)
    assert smtp.calls == ["connect", "ehlo", "starttls", "ehlo", "login", "send", "quit"]
    message = smtp.sent
    assert message["Subject"] == "UBER entró en 4X DCA"
    assert message["To"] == "nico@example.test, otro@example.test"
    assert message.is_multipart()
    types = [part.get_content_type() for part in message.iter_parts()]
    assert types == ["text/plain", "text/html"]


def test_ssl_mode_skips_starttls():
    result = send_email(
        _settings(smtp_ssl=True, smtp_port=465), _content(), smtp_ssl_factory=FakeSMTP
    )
    assert result["status"] == "delivered"
    assert "starttls" not in FakeSMTP.instances[0].calls


def test_partial_refusal_is_delivered_with_note():
    FakeSMTP.refused = {"otro@example.test": (550, b"no")}
    result = send_email(_settings(), _content(), smtp_factory=FakeSMTP)
    assert result["status"] == "delivered"
    assert "Rechazados 1" in result["error"]


@pytest.mark.parametrize(
    ("step", "exc", "status"),
    [
        ("login", smtplib.SMTPAuthenticationError(535, b"bad credentials"), "failed"),
        ("send", smtplib.SMTPDataError(554, b"rechazado"), "failed"),
        ("send", smtplib.SMTPDataError(451, b"espera"), "throttled"),
        ("send", smtplib.SMTPRecipientsRefused({"a@b": (550, b"no")}), "failed"),
        ("send", TimeoutError("timed out"), "unknown"),
        ("send", smtplib.SMTPServerDisconnected("cortado"), "unknown"),
        ("connect", ConnectionRefusedError(111, "refused"), "pending"),
        ("connect", TimeoutError("connect timeout"), "pending"),
        ("starttls", smtplib.SMTPNotSupportedError("no tls"), "failed"),
    ],
)
def test_error_classification(step, exc, status):
    FakeSMTP.fail_at, FakeSMTP.exc = step, exc
    result = send_email(_settings(), _content(), smtp_factory=FakeSMTP)
    assert result["status"] == status
    # Nunca se filtra la contrasena ni el cuerpo del servidor.
    assert "secreto" not in (result["error"] or "")
    assert "bad credentials" not in (result["error"] or "")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = None
        yield session


def _alert(db, *, alert_type="price_above", metadata=None):
    alert = ResearchAlert(
        alert_type=alert_type, severity="high", title="AAPL: price_above > 200",
        message="AAPL rule matched", fingerprint=f"fp-{alert_type}", channels=["in_app", "email"],
        metadata_=metadata or {},
    )
    db.add(alert)
    db.commit()
    return alert


def test_dispatch_uses_smtp_when_configured(db, monkeypatch):
    sent: list[EmailContent] = []
    monkeypatch.setattr(
        "app.services.notification_service.get_settings", lambda: _settings(telegram_enabled=False)
    )

    def fake_send(settings, content, **kwargs):
        sent.append(content)
        return {"status": "delivered", "error": None}

    monkeypatch.setattr("app.services.notification_service.send_email", fake_send)
    alert = _alert(db)
    deliveries = NotificationService().dispatch(db, alert)
    assert deliveries["email"]["status"] == "delivered"
    assert sent[0].subject == "[GerarAI] AAPL: price_above > 200"
    row = db.scalar(select(AlertDelivery).where(AlertDelivery.channel == "email"))
    assert row is not None and row.status == "delivered"


def test_dispatch_maps_smtp_failure_to_outbox(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.notification_service.get_settings", lambda: _settings(telegram_enabled=False)
    )
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.fail_at, FakeSMTP.exc = "login", smtplib.SMTPAuthenticationError(535, b"no")
    alert = _alert(db)
    deliveries = NotificationService().dispatch(db, alert)
    assert deliveries["email"]["status"] == "failed"
    assert deliveries["email"]["error"] == "SMTPAuthenticationError 535"


def test_dca_alert_uses_dca_template(db, monkeypatch):
    sent: list[EmailContent] = []
    monkeypatch.setattr(
        "app.services.notification_service.get_settings", lambda: _settings(telegram_enabled=False)
    )
    monkeypatch.setattr(
        "app.services.notification_service.send_email",
        lambda settings, content, **kw: sent.append(content) or {"status": "delivered", "error": None},
    )
    dca = {
        "symbol": "UBER", "company_name": "Uber Technologies", "level": 4, "label": "4X DCA",
        "zone": "Zona de compra extrema", "color": "#B400FF", "fg": "#FFFFFF", "status": "forming",
        "signal_date": "2026-10-26", "close": 66.13, "currency": "USD",
        "metrics": {"signal": "sma_gap", "sma_gap": 0.125, "rsi": 38.2},
        "level_prices": {"2x": 72.0, "3x": 68.4, "4x": 64.8}, "sma_months": 40,
    }
    alert = _alert(db, alert_type="dca_level", metadata={"dca": dca})
    NotificationService().dispatch(db, alert)
    content = sent[0]
    assert content.subject.startswith("UBER entró en 4X DCA")
    assert "#B400FF" in (content.html or "")
    assert "mes en formación" in content.text
    assert "66,13 USD" in content.text
    assert "Distancia bajo media 40m: 12,5 %" in content.text
    assert "no asesoramiento financiero" in content.text


def test_email_falls_back_to_webhook_when_smtp_unset(db):
    # Sin SMTP (conftest deja SMTP_* vacios) el canal sigue el camino webhook.
    alert = _alert(db)
    deliveries = NotificationService().dispatch(db, alert)
    assert deliveries["email"]["status"] == "not_configured"
    assert "No webhook configured" in deliveries["email"]["error"]
