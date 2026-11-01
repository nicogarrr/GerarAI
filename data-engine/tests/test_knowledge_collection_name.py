"""POST /api/knowledge/collections: un nombre sin letras ni numeros ASCII
(«!!», «日本株») respondia 409 «ya existe» aunque no existiera nada; ahora es
un 422 que dice por que. El duplicado real sigue siendo 409."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "knowledge-collection-name-test-secret-32ch"


def _client(monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    init_db()
    tenant_ext = f"kcol-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Knowledge collection name"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext


def _post(client: TestClient, tenant: str, name: str):
    return signed_request(
        client, SECRET, tenant, "kcol-user", "POST", "/api/knowledge/collections",
        json_body={"name": name},
    )


def test_nombre_sin_letras_no_dice_que_ya_existe(monkeypatch) -> None:
    client, tenant = _client(monkeypatch)
    for name in ("!!", "日本株", "€ €"):
        res = _post(client, tenant, name)
        assert res.status_code == 422, (name, res.status_code, res.text)
        assert "already exists" not in res.text


def test_duplicado_real_sigue_siendo_409(monkeypatch) -> None:
    client, tenant = _client(monkeypatch)
    first = _post(client, tenant, "Value investing")
    assert first.status_code == 200, first.text
    again = _post(client, tenant, "value  INVESTING")
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == "Knowledge collection already exists"
