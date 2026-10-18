"""POST /api/ownership/managers/sync-async encola el actor y responde 202."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant

SECRET = "ownership-sync-async-test-secret-at-least-32-chars"

from tests.auth_helpers import auth_settings, signed_request


def _fake_message_id() -> str:
    return "fake-broker-message-id"


class _FakeActor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)

        class _Message:
            message_id = _fake_message_id()

        return _Message()


def test_sync_async_enqueues_actor_with_tenant_context(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    from app.workers import dramatiq_app

    fake = _FakeActor()
    monkeypatch.setattr(dramatiq_app, "sync_investor_holdings", fake)

    init_db()
    tenant_ext = f"sync-async-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Sync async test"))
    db.commit()
    db.close()

    client = TestClient(main.app)
    user = "sync-async-user"
    res = signed_request(client, SECRET, tenant_ext, user, "POST", "/api/ownership/managers/sync-async")
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "queued"
    assert body["broker_message_id"]

    # El actor recibe el contexto de tenant/usuario del firmante de la peticion.
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["tenant_id"] is not None
    assert call["user_id"] == user
