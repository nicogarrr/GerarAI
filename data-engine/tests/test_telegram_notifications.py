from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.services import notification_service
from app.services.public_fetch import validate_public_url


class _FakeResponse:
    def json(self):
        return {"ok": True}

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    calls: list[tuple[str, dict]] = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url: str, json: dict):
        self.calls.append((url, json))
        return _FakeResponse()


class _FakeDB:
    def commit(self) -> None:
        return None

    def refresh(self, _alert) -> None:
        return None



def _service_with_stubbed_outbox():
    """NotificationService con el outbox (alert_deliveries) stubado.

    Estos tests cubren el canal Telegram (texto, config, 429); la capa de
    claim atomico tiene sus propios tests con SQLite real en
    test_notification_service.py.
    """
    svc = notification_service.NotificationService()
    svc._ensure_delivery_row = lambda db, alert, channel: None
    svc._claim_delivery = lambda db, alert, channel: True
    svc._finish_delivery = lambda db, alert, channel, status, error, retry_after=None: None
    return svc

def _alert(channels: list[str]):
    # nosemgrep: gerarai-orm-fake-simplenamespace -- formato del mensaje: el servicio solo lee atributos de la alerta
    return SimpleNamespace(
        id=7,
        tenant_id=3,
        company_id=11,
        severity="high",
        alert_type="news",
        title="Material company news",
        message="A material event was detected.",
        created_at=datetime.now(UTC),
        channels=channels,
        metadata_={},
    )


def test_telegram_notification_uses_configured_channel_without_leaking_token(monkeypatch):
    _FakeClient.calls.clear()
    monkeypatch.setattr(notification_service.httpx, "Client", _FakeClient)
    monkeypatch.setattr(
        notification_service,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_enabled=True,
            telegram_bot_token="rotated-test-token",
            telegram_chat_id="12345",
            telegram_api_base_url="https://api.telegram.org",
            telegram_timeout_seconds=10,
        ),
    )

    result = notification_service.NotificationService()._dispatch_telegram(
        notification_service.get_settings(), {"severity": "high", "title": "Material company news",
        "message": "A material event was detected.", "company_id": 11, "alert_id": 7, "chat_id": "12345"})

    assert result["status"] == "delivered"
    url, body = _FakeClient.calls[0]
    assert url.endswith("/sendMessage")
    assert body["chat_id"] == "12345"
    assert "Material company news" in body["text"]
    assert "rotated-test-token" not in body["text"]


def test_telegram_notification_is_silent_when_not_configured(monkeypatch):
    monkeypatch.setattr(
        notification_service,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_enabled=False,
            telegram_bot_token=None,
            telegram_chat_id=None,
            telegram_api_base_url="https://api.telegram.org",
            telegram_timeout_seconds=10,
        ),
    )

    result = notification_service.NotificationService()._dispatch_telegram(
        notification_service.get_settings(), {"severity": "high", "title": "Material company news",
        "message": "A material event was detected.", "company_id": 11, "alert_id": 7, "chat_id": "12345"})

    assert result["status"] == "not_configured"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/internal",
        "http://localhost/internal",
        "http://169.254.169.254/latest/meta-data",
        "https://user:password@example.com/private",
    ],
)
def test_public_fetch_rejects_private_or_credential_urls(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


class _RateLimitedClient:
    """Telegram devuelve 429: sin reintento en el fuente, un solo intento."""

    attempts = 0

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url: str, json: dict):
        type(self).attempts += 1
        request = httpx.Request("POST", url, json=json)
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError(
            "429 Too Many Requests", request=request, response=response
        )


def test_telegram_429_fails_honestly_without_retry_storm(monkeypatch):
    """429 → 'throttled' honesto: el servicio no reintenta en caliente (sin
    backoff en el fuente; la fila enfria y solo vuelve via reconciliador por
    claim expirado) y persiste solo la clase de error, nunca el token ni el
    body."""
    _RateLimitedClient.attempts = 0
    monkeypatch.setattr(notification_service.httpx, "Client", _RateLimitedClient)
    monkeypatch.setattr(
        notification_service,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_enabled=True,
            telegram_bot_token="rotated-test-token",
            telegram_chat_id="12345",
            telegram_api_base_url="https://api.telegram.org",
            telegram_timeout_seconds=10,
        ),
    )

    result = notification_service.NotificationService()._dispatch_telegram(
        notification_service.get_settings(), {"severity": "high", "title": "Material company news",
        "message": "A material event was detected.", "company_id": 11, "alert_id": 7, "chat_id": "12345"})

    delivery = result
    assert delivery["status"] == "throttled"
    assert delivery["error"] == "HTTPStatusError"
    assert _RateLimitedClient.attempts == 1
    assert "rotated-test-token" not in str(result)


def test_news_telegram_uses_source_metadata_without_machine_trace():
    from app.services.notification_service import NotificationService
    text = NotificationService._telegram_text({
        "severity": "high", "title": "Review required: news material update",
        "message": "No structural thesis node matched", "company_name": "Visa", "ticker": "V",
        "type": "news_material_update", "source_headline": "V 8-K filed 2025-10-28",
        "event_date": datetime(2025, 10, 28, tzinfo=UTC), "event_date_source": "source",
        "source_url": "https://www.sec.gov/x", "alert_id": 1, "company_id": 1,
    })
    assert text.startswith("Visa · 8-K · 28/10/2025")
    assert "Documento 8-K asociado a Visa" in text
    assert "Abrir documento: https://www.sec.gov/x" in text
    assert "No structural thesis" not in text


def test_news_telegram_in_english_when_alert_language_is_english():
    from app.services.notification_service import NotificationService
    base = {
        "severity": "high", "title": "t", "message": "m", "company_name": "Visa", "ticker": "V",
        "type": "news_material_update", "source_headline": "V 8-K filed 2025-10-28",
        "event_date": datetime(2025, 10, 28, tzinfo=UTC), "event_date_source": "gdelt_first_seen",
        "source_url": "https://www.sec.gov/x", "alert_id": 1, "company_id": 1, "language": "en",
    }
    text = NotificationService._telegram_text(base)
    assert text.startswith("Visa · 8-K · detected 28/10/2025")
    assert "8-K filing linked to Visa; check the source before changing the thesis." in text
    assert "See affected thesis: V (in the app)" in text
    assert "Open document: https://www.sec.gov/x" in text
    news = NotificationService._telegram_text({**base, "type": "tracked_news", "source_headline": "Visa expands"})
    assert news.startswith("Visa · News · detected 28/10/2025")
    assert "News about Visa; check the source before drawing conclusions." in news
    spanish = NotificationService._telegram_text({k: v for k, v in base.items() if k != "language"})
    assert "Documento 8-K asociado a Visa" in spanish and "detectada 28/10/2025" in spanish


def test_generic_alert_email_in_english_when_alert_language_is_english():
    from app.services.email_delivery import generic_alert_content

    payload = {"severity": "low", "title": "", "message": "UBER entered 3X DCA", "ticker": "UBER"}
    english = generic_alert_content({**payload, "language": "en"})
    assert english.subject == "[GerarAI] Alert"
    assert "Open GerarAI to see the alert details." in english.text
    assert "Open GerarAI to see the alert details." in english.html
    spanish = generic_alert_content(payload)
    assert spanish.subject == "[GerarAI] Alerta"
    assert "Abre GerarAI para ver el detalle de la alerta." in spanish.text



def test_dispatch_wraps_generic_email_in_saved_alert_language(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.models import ResearchAlert, Tenant
    from app.models.entities import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sent = []
    monkeypatch.setattr(notification_service, "smtp_configured", lambda settings: True)
    monkeypatch.setattr(notification_service, "send_email", lambda settings, c: sent.append(c) or {"status": "delivered"})
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id="owner"))
        db.commit()
        db.info.update(tenant_id=1, user_id="owner")
        for i, meta in enumerate(({"language": "en"}, {})):
            alert = ResearchAlert(tenant_id=1, alert_type="price_rule", severity="low", status="open", title="",
                                  message="UBER above 80", fingerprint=f"fp-{i}", channels=["email"], metadata_=meta)
            db.add(alert)
            db.commit()
            notification_service.NotificationService().dispatch(db, alert)
    engine.dispose()
    assert [c.subject for c in sent] == ["[GerarAI] Alert", "[GerarAI] Alerta"]
