"""Auto-encolado 13F del primer uso sin datos (una vez por ventana)."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Tenant
from app.models.entities import FundManager
from app.services import investor_autosync
from tests.auth_helpers import auth_settings, signed_request

SECRET = "investor-autosync-test-secret-at-least-32-chars"


class _FakeRedis:
    def __init__(self, claimed: bool = True) -> None:
        self.claimed = claimed
        self.sets: list[dict] = []

    def set(self, key, value, nx=False, ex=None):
        self.sets.append({"key": key, "value": value, "nx": nx, "ex": ex})
        return self.claimed


class _FakeActor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)

        class _Message:
            message_id = "fake-broker-message-id"

        return _Message()


def _tenant_db() -> tuple[str, object]:
    init_db()
    ext = f"autosync-{uuid4().hex[:8]}"
    db = SessionLocal()
    db.add(Tenant(external_id=ext, name="Autosync test"))
    db.commit()
    db.close()
    db = SessionLocal()
    db.info["tenant_id"] = ext
    db.info["user_id"] = "autosync-user"
    return ext, db


def _patch(monkeypatch, redis_client, actor):
    from app.workers import dramatiq_app

    monkeypatch.setattr(dramatiq_app, "_redis_client", lambda: redis_client)
    monkeypatch.setattr(dramatiq_app, "sync_investor_holdings", actor)


def test_encola_cuando_el_tenant_no_tiene_gestores(monkeypatch):
    ext, db = _tenant_db()
    redis, actor = _FakeRedis(claimed=True), _FakeActor()
    _patch(monkeypatch, redis, actor)
    assert investor_autosync.maybe_autosync_holdings(db) is True
    assert actor.calls == [{"tenant_id": ext, "user_id": "autosync-user"}]
    assert redis.sets == [{
        "key": f"autosync:investor-holdings:{ext}",
        "value": "1",
        "nx": True,
        "ex": investor_autosync.COOLDOWN_SECONDS,
    }]
    db.close()


def test_no_encola_si_ya_hay_gestor_descargado(monkeypatch):
    ext, db = _tenant_db()
    db.add(FundManager(cik="0001067983", name="Berkshire Hathaway"))
    db.commit()
    redis, actor = _FakeRedis(claimed=True), _FakeActor()
    _patch(monkeypatch, redis, actor)
    assert investor_autosync.maybe_autosync_holdings(db) is False
    assert actor.calls == [] and redis.sets == []
    db.close()


def test_no_reencola_dentro_de_la_ventana(monkeypatch):
    ext, db = _tenant_db()
    redis, actor = _FakeRedis(claimed=False), _FakeActor()
    _patch(monkeypatch, redis, actor)
    assert investor_autosync.maybe_autosync_holdings(db) is False
    assert actor.calls == []
    db.close()


def test_sin_redis_no_encola(monkeypatch):
    ext, db = _tenant_db()
    actor = _FakeActor()
    _patch(monkeypatch, None, actor)
    assert investor_autosync.maybe_autosync_holdings(db) is False
    assert actor.calls == []
    db.close()


def test_un_fallo_del_broker_nunca_rompe_la_lectura(monkeypatch):
    ext, db = _tenant_db()

    class _Exploding:
        def send(self, **kwargs):
            raise RuntimeError("broker caido")

    _patch(monkeypatch, _FakeRedis(claimed=True), _Exploding())
    assert investor_autosync.maybe_autosync_holdings(db) is False
    db.close()


def test_get_investors_dispara_el_autoencolado(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: auth_settings(strict=True, secret=SECRET),
    )
    ext, db = _tenant_db()
    db.close()
    redis, actor = _FakeRedis(claimed=True), _FakeActor()
    _patch(monkeypatch, redis, actor)
    client = TestClient(main.app)
    res = signed_request(client, SECRET, ext, "autosync-user", "GET", "/api/investors")
    assert res.status_code == 200, res.text
    # En contexto de peticion db.info lleva el id interno del tenant.
    assert len(actor.calls) == 1
    assert actor.calls[0]["tenant_id"] is not None
    assert actor.calls[0]["user_id"] == "autosync-user"
