"""Pasada bespoke del contrato «fallo de sesion = error estructurado».

Los tres actores que no seguian la forma mecanica de #5656:
- analyze_tracked_news_alert: la sesion se abria antes del lease, sin try.
- sync_ibkr_flex: la sesion se abria tras la descarga, sin try.
- refresh_subtel_decrees: un fallo de _session de UN tenant mataba el
  bucle y dejaba a los demas tenants sin decretos; ahora queda anotado
  por tenant (mismo contrato «failures are visible» que persist_decrees).

Run from data-engine/:
    pytest tests/test_worker_session_bespoke.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import config as config_module
from app.core import database as database_module
from app.services import subtel_news
from app.services.connectors import ibkr as ibkr_module
from app.services.connectors import subtel
from app.workers import dramatiq_app as worker

BOOM = ValueError("tenant_id and user_id are required for background jobs")


@pytest.fixture()
def env(monkeypatch):
    e = SimpleNamespace(rolled=[], handled=[], session_error=None, dbs=[])

    def session(tenant, user):
        if e.session_error and e.session_error[0] == tenant:
            raise e.session_error[1]
        db = MagicMock()
        db.info = {"tenant_id": tenant}
        e.dbs.append(db)
        return db

    def handle(actor, exc, **ctx):
        e.handled.append((actor, exc, ctx))
        return {"status": "error", "actor": actor, "error": {"type": type(exc).__name__}}

    monkeypatch.setattr(worker, "_session", session)
    monkeypatch.setattr(worker, "_rollback", lambda db: e.rolled.append(db))
    monkeypatch.setattr(worker, "_handle_actor_error", handle)
    monkeypatch.setattr(worker, "_redis_client", lambda: None)
    monkeypatch.setattr(worker, "_lease_redis_url", lambda: None)
    monkeypatch.setattr(worker, "acquire_job_lease", lambda key, **kw: "LEASE")
    monkeypatch.setattr(worker, "release_job_lease", lambda key, lease, **kw: None)
    return e


def test_analyze_tracked_news_sesion_estructurada(env, monkeypatch):
    env.session_error = (1, BOOM)
    called = []
    monkeypatch.setattr("app.services.alert_analysis_service.analyze_alert", lambda db, aid: called.append(aid))

    out = worker.analyze_tracked_news_alert.fn(42, tenant_id=1, user_id="u")

    assert out["status"] == "error"
    assert out["actor"] == "analyze_tracked_news_alert"
    assert called == []


def test_sync_ibkr_flex_sesion_estructurada(env, monkeypatch):
    env.session_error = (7, BOOM)
    settings = SimpleNamespace(
        ibkr_flex_tenant_id=7, ibkr_flex_account_id="U1",
        ibkr_flex_complete_query_id="Q1", ibkr_flex_query_id="Q1",
    )
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    admin = MagicMock()
    admin.scalar.return_value = None  # sin conector por tenant: aplica el global
    admin.__enter__.return_value = admin
    admin.__exit__.return_value = False
    monkeypatch.setattr(database_module, "SessionLocal", lambda: admin)

    class Client:
        def configured(self):
            return True

        def fetch_latest_xml(self):
            return "xml"

    monkeypatch.setattr(ibkr_module, "IBKRFlexClient", Client)
    monkeypatch.setattr(worker, "_run", lambda coro: "<xml/>")
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(7, "u")])

    out = worker.sync_ibkr_flex.fn()

    assert out["status"] == "error"
    assert out["actor"] == "sync_ibkr_flex"
    assert env.handled and env.handled[0][1] is BOOM


def test_subtel_fallo_de_sesion_de_un_tenant_no_frena_al_resto(env, monkeypatch):
    env.session_error = (2, BOOM)
    persisted = []
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "one"), (2, "two"), (3, "three")])

    async def fetch(client=None):
        return [{"marker": "official"}]

    def persist(db, rows, fetched_at):
        persisted.append(db.info["tenant_id"])
        return 1

    monkeypatch.setattr(subtel, "fetch_decrees", fetch)
    monkeypatch.setattr(subtel_news, "persist_decrees", persist)

    out = worker.refresh_subtel_decrees.fn()

    assert out["status"] == "partial"
    assert out["created"] == 2
    assert persisted == [1, 3]
    assert out["errors"] == [{"tenant_id": 2, "type": "ValueError"}]
    for db in env.dbs:
        db.close.assert_called_once_with()
