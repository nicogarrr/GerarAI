"""GET /api/alerts/telegram-status con response_model.

Forma medida contra la ruta: cuatro booleanos siempre (enabled,
has_bot_token, has_chat_id, configured); solo presencia de config, ningun
secreto sale por la API. configured es la conjuncion de los otros tres
(invariante de la ruta).
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "alerts-telegram-status-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"alerts-telegram-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Alerts telegram test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "alerts-telegram-user"


def test_telegram_status_envelope(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/alerts/telegram-status")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert set(payload) == {"enabled", "has_bot_token", "has_chat_id", "configured"}
    assert all(isinstance(v, bool) for v in payload.values())
    # Invariante medida: configured es la conjuncion de los otros tres.
    assert payload["configured"] == (
        payload["enabled"] and payload["has_bot_token"] and payload["has_chat_id"]
    )
