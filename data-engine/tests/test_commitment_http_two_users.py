"""HTTP firmado con dos usuarios y dos tenants: notas privadas aisladas (sintetico, sin red)."""

from __future__ import annotations

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.seed import seed
from tests.auth_helpers import auth_settings, bound_headers

SECRET = "commitments-http-test-secret-at-least-32-chars"


def _call(client, method, path, tenant, user, json_body=None):
    import json as _json

    body = b"" if json_body is None else _json.dumps(json_body).encode()
    headers = bound_headers(SECRET, tenant, user, method=method, path=path, body=body)
    headers["content-type"] = "application/json"
    return client.request(method, path, content=body or None, headers=headers)


def test_private_notes_isolated_over_signed_http(monkeypatch):
    seed()
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET)
    )
    client = TestClient(main.app)
    base = "/api/companies/MSFT/management-credibility"
    unsigned = client.get(f"{base}/notes")
    assert unsigned.status_code == 401

    created = _call(
        client, "POST", f"{base}/promises", "tenant-a", "user-a",
        {"promise": "Synthetic promise for isolation test", "promise_date": "2026-01-15", "expected_period": "FY2026"},
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    note = _call(client, "POST", f"{base}/promises/{pid}/notes", "tenant-a", "user-a",
                 {"body": "nota privada A"})
    assert note.status_code == 201, note.text

    own = _call(client, "GET", f"{base}/promises/{pid}/notes", "tenant-a", "user-a")
    assert own.status_code == 200 and "nota privada A" in own.text
    batch_own = _call(client, "GET", f"{base}/notes", "tenant-a", "user-a")
    assert "nota privada A" in batch_own.text

    other_user = _call(client, "GET", f"{base}/promises/{pid}/notes", "tenant-a", "user-b")
    assert "nota privada A" not in other_user.text
    batch_other_user = _call(client, "GET", f"{base}/notes", "tenant-a", "user-b")
    assert "nota privada A" not in batch_other_user.text

    other_tenant = _call(client, "GET", f"{base}/promises/{pid}/notes", "tenant-b", "user-a")
    assert "nota privada A" not in other_tenant.text
    batch_other_tenant = _call(client, "GET", f"{base}/notes", "tenant-b", "user-a")
    assert "nota privada A" not in batch_other_tenant.text
