"""POST /api/knowledge/corpus/ingest-async encola el actor y responde 202."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant

SECRET = "corpus-ingest-async-test-secret-at-least-32-chars"

from tests.auth_helpers import auth_settings, signed_request


class _FakeActor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)

        class _Message:
            message_id = "fake-corpus-message-id"

        return _Message()


def test_corpus_ingest_async_enqueues_actor_with_tenant_context(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    from app.workers import dramatiq_app

    fake = _FakeActor()
    monkeypatch.setattr(dramatiq_app, "ingest_letters_corpus", fake)

    init_db()
    tenant_ext = f"corpus-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Corpus ingest test"))
    db.commit()
    db.close()

    client = TestClient(main.app)
    user = "corpus-ingest-user"
    res = signed_request(client, SECRET, tenant_ext, user, "POST", "/api/knowledge/corpus/ingest-async")
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "queued"
    assert body["broker_message_id"]

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["tenant_id"] is not None
    assert call["user_id"] == user
