"""GET /api/watchlist/attention-thesis con response_model.

Forma medida contra la ruta y home_attention_service.pending_thesis_changes:
envelope fijo {items, truncated}; item de 5 claves siempre (id, symbol,
summary, direction, createdAt). direction es String(40) con escritores
neutral/negative/mixed medidos; no es conjunto cerrado: str honesto.
Servicio real, sin mock.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.schemas.api import WatchlistAttentionThesisOut
from tests.auth_helpers import auth_settings, signed_request

SECRET = "watchlist-attention-thesis-secret-"


def _client(monkeypatch) -> tuple[TestClient, str, str]:
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"watchlist-attention-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Watchlist attention test"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext, "watchlist-attention-user"


def test_attention_thesis_empty_wire(monkeypatch) -> None:
    client, tenant, user = _client(monkeypatch)

    res = signed_request(client, SECRET, tenant, user, "GET", "/api/watchlist/attention-thesis")

    assert res.status_code == 200, res.text
    payload = res.json()
    WatchlistAttentionThesisOut.model_validate(payload)
    # Envelope fijo: exactamente dos claves.
    assert set(payload) == {"items", "truncated"}
    # Sin watchlist ni posiciones: bandeja vacia, nunca truncada.
    assert payload["items"] == []
    assert payload["truncated"] is False
