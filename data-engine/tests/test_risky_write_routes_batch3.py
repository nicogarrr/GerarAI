"""Rutas de escritura de riesgo sin test directo (lote 3).

- POST /api/settings/ibkr/sync: sincroniza cartera real desde IBKR
  (credenciales + dinero). Sin conexion guardada: 422 honesto que conserva
  los datos anteriores; sync en curso: 409.
- POST /api/ownership/schedule-13dg/sync: ingesta acotada a tickers
  SEGUIDOS; cualquier otro se rechaza 404 en vez de gastar peticiones a la
  SEC en un emisor que el usuario no sigue (frontera de alcance).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from tests.auth_helpers import auth_settings, signed_request

SECRET = "risky-write-routes-b3-test-secret-at-least-32-chars"


def _client_with_tenant(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    init_db()
    tenant_ext = f"risky-b3-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=tenant_ext, name="Risky b3"))
    db.commit()
    db.close()
    return TestClient(main.app), tenant_ext


def test_ibkr_sync_without_connection_is_honest_422(monkeypatch):
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/settings/ibkr/sync")
    assert res.status_code == 422, res.text
    # Nunca un 500 ni un "ok" inventado: el fallo es explicito y conserva datos.
    assert "IBKR" in res.text or "ibkr" in res.text


def test_ibkr_sync_busy_returns_409(monkeypatch):
    from contextlib import contextmanager

    from app.services import ibkr_connection_service as ibkr

    @contextmanager
    def _busy(db):
        raise ibkr.SyncBusy("Ya hay una sincronización IBKR en curso.")
        yield

    monkeypatch.setattr(ibkr, "sync_lease", _busy)
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(client, SECRET, tenant, "u1", "POST", "/api/settings/ibkr/sync")
    assert res.status_code == 409, res.text


def test_schedule13dg_sync_rejects_unfollowed_ticker(monkeypatch):
    client, tenant = _client_with_tenant(monkeypatch)
    res = signed_request(
        client, SECRET, tenant, "u1", "POST", "/api/ownership/schedule-13dg/sync",
        params={"ticker": "NOPE"},
    )
    assert res.status_code == 404, res.text
