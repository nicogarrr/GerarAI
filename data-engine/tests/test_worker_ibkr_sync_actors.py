"""sync_one_tenant_ibkr y sync_tenant_ibkr_connections: flujo feliz,
not_ready que reintenta una hora despues (o se sella en el ultimo),
errores no transitorios sin reintento, lease ocupado, y el dispatch
diario que encola solo tenants con conexion habilitada."""

from contextlib import contextmanager
from types import SimpleNamespace

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.ibkr_connection_service as ibkr
import app.workers.rate_limit_retry as rlr
from app.models.entities import Base, Tenant
from app.models.ibkr_connection import IBKRConnection
from app.workers import dramatiq_app as worker


class FakeErr(Exception):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    monkeypatch.setattr(worker, "_session", lambda tenant, user: db)
    e = SimpleNamespace(db=db, failures=[], import_result={"status": "ok"},
                        download_error=None, busy=False, exhausted=False,
                        credentials_ok=True)

    @contextmanager
    def fake_lease(db_):
        if e.busy:
            raise ibkr.SyncBusy("ocupado")
        yield

    monkeypatch.setattr(ibkr, "sync_lease", fake_lease)
    monkeypatch.setattr(ibkr, "credentials",
                        lambda db_, settings: ("tok", "q1", "acc", 7))
    monkeypatch.setattr(ibkr, "start_receipt", lambda db_, revision, origin=None: 42)

    async def fake_download(token, query_id):
        if e.download_error is not None:
            raise e.download_error
        return "<xml/>"

    monkeypatch.setattr(ibkr, "download", fake_download)
    monkeypatch.setattr(ibkr, "import_report",
                        lambda db_, xml, account_id, revision, receipt_id=None: e.import_result)
    monkeypatch.setattr(ibkr, "error_kind",
                        lambda exc: getattr(exc, "kind", "timeout"))
    monkeypatch.setattr(ibkr, "record_failure",
                        lambda db_, revision, receipt_id=None, error_code=None:
                        e.failures.append(error_code))
    monkeypatch.setattr(rlr, "retries_exhausted", lambda: e.exhausted)
    return e


def test_flujo_feliz_devuelve_el_resultado_del_servicio(env):
    out = worker.sync_one_tenant_ibkr.fn(tenant_id=1, user_id="u")
    assert out == {"status": "ok"}
    assert env.failures == []


def test_not_ready_reintenta_una_hora_despues(env):
    env.download_error = FakeErr("not_ready")
    with pytest.raises(dramatiq.Retry):
        worker.sync_one_tenant_ibkr.fn(tenant_id=1, user_id="u")
    assert env.failures == ["not_ready"]


def test_not_ready_en_el_ultimo_intento_se_sella_sin_dead_letter(env):
    env.download_error = FakeErr("not_ready")
    env.exhausted = True
    out = worker.sync_one_tenant_ibkr.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and out["reason"] == "pnl_not_ready"


def test_error_no_transitorio_no_reintenta(env):
    env.download_error = FakeErr("bad_credentials")
    out = worker.sync_one_tenant_ibkr.fn(tenant_id=1, user_id="u")
    assert out["status"] == "error" and "anteriores" in out["message"]
    assert env.failures == ["bad_credentials"]


def test_lease_ocupado_devuelve_busy(env):
    env.busy = True
    out = worker.sync_one_tenant_ibkr.fn(tenant_id=1, user_id="u")
    assert out["status"] == "busy"


@pytest.fixture()
def dispatch_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    import app.core.database as core_db

    monkeypatch.setattr(core_db, "SessionLocal", lambda: db)
    e = SimpleNamespace(db=db, sends=[], dedicated=False)
    monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "u"), (2, "u")])
    # dramatiq_app importa get_settings en el modulo: hay que parchear SU referencia.
    monkeypatch.setattr(worker, "get_settings",
                        lambda: SimpleNamespace(ibkr_dedicated_sync_enabled=e.dedicated))
    monkeypatch.setattr(worker, "sync_one_tenant_ibkr", SimpleNamespace(
        send=lambda *a: e.sends.append(("plain",) + a)))
    monkeypatch.setattr(worker, "sync_one_tenant_ibkr_dedicated", SimpleNamespace(
        send=lambda *a: e.sends.append(("dedicated",) + a)))
    return e


def _connection(db, tenant_id, enabled=True):
    db.add(Tenant(id=tenant_id, external_id=f"ext-{tenant_id}", name=f"t{tenant_id}"))
    db.add(IBKRConnection(tenant_id=tenant_id, query_id="q", account_id="a",
                          enabled=enabled))
    db.commit()


def test_dispatch_solo_tenants_con_conexion_habilitada(dispatch_env):
    _connection(dispatch_env.db, 1, enabled=True)
    _connection(dispatch_env.db, 2, enabled=False)
    out = worker.sync_tenant_ibkr_connections.fn()
    assert out == {"scheduled": 1}
    assert dispatch_env.sends == [("plain", 1, "u")]


def test_dispatch_usa_el_actor_dedicado_si_esta_activo(dispatch_env):
    dispatch_env.dedicated = True
    _connection(dispatch_env.db, 1, enabled=True)
    out = worker.sync_tenant_ibkr_connections.fn()
    assert out == {"scheduled": 1}
    assert dispatch_env.sends == [("dedicated", 1, "u")]


def test_dispatch_error_devuelve_payload(dispatch_env, monkeypatch):
    import app.core.database as core_db

    def boom():
        raise RuntimeError("pg caido")

    monkeypatch.setattr(core_db, "SessionLocal", boom)
    out = worker.sync_tenant_ibkr_connections.fn()
    assert out["status"] == "error"
    assert out["actor"] == "sync_tenant_ibkr_connections"
