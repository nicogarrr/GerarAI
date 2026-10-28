"""Actor sync_ibkr_flex: el token global solo sirve al tenant configurado, no
revive credenciales tras desconectar y distingue errores permanentes, PyG
diferido (reintento en 1 h) y fallos transitorios.

Run from data-engine/:
    pytest tests/test_worker_sync_ibkr_flex.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import dramatiq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config as config_module
from app.core import database as database_module
from app.core.database import Base
from app.models import IBKRConnection  # noqa: F401  (registra la tabla)
from app.services import ibkr_import_service as import_module
from app.services.connectors import ibkr as ibkr_module
from app.workers import dramatiq_app as worker

RESULT = {
    "status": "ok", "positions_imported": 3, "cash_imported": 2, "trades_imported": 5,
    "rows_skipped": 1, "row_errors": [{"row": 1}], "positions_closed": 1, "cash_removed": 0,
    "reconcile_blocked": False,
}


class _Env:
    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.settings = SimpleNamespace(
            ibkr_flex_tenant_id=7, ibkr_flex_account_id=" U123 ",
            ibkr_flex_complete_query_id="Q1", ibkr_flex_query_id="Q1",
        )
        self.configured = True
        self.fetch_error = None
        self.import_error = None
        self.import_kwargs = None
        self.db = MagicMock()
        engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        self.admin_factory = sessionmaker(bind=engine)
        monkeypatch.setattr(config_module, "get_settings", lambda: self.settings)
        monkeypatch.setattr(database_module, "SessionLocal", self.admin_factory)
        env = self

        class Client:
            def configured(self):
                return env.configured

            def fetch_latest_xml(self):
                return "xml"

        monkeypatch.setattr(ibkr_module, "IBKRFlexClient", Client)

        class Service:
            def import_flex_xml(self, db, xml, **kw):
                env.import_kwargs = kw
                if env.import_error:
                    raise env.import_error
                return dict(RESULT)

        monkeypatch.setattr(import_module, "IBKRImportService", Service)
        monkeypatch.setattr(worker, "tenant_contexts", lambda: [(1, "other"), (7, "owner-user")])

        def fake_run(_coro):
            if env.fetch_error:
                raise env.fetch_error
            return "<xml/>"

        monkeypatch.setattr(worker, "_run", fake_run)
        monkeypatch.setattr(worker, "_session", lambda tenant, user: env.db)
        self.rolled = []
        monkeypatch.setattr(worker, "_rollback", lambda db: self.rolled.append(db))


@pytest.fixture()
def env(monkeypatch):
    return _Env(monkeypatch)


def _call():
    return worker.sync_ibkr_flex.fn()


def test_not_configured_variants_skip_without_touching_db(env):
    env.configured = False
    assert _call() == {"actor": "sync_ibkr_flex", "status": "skipped", "reason": "not_configured"}
    env.configured = True
    env.settings.ibkr_flex_tenant_id = None
    assert _call()["reason"] == "not_configured"
    env.settings.ibkr_flex_tenant_id = 7
    env.settings.ibkr_flex_account_id = "   "
    assert _call()["reason"] == "not_configured"
    assert env.import_kwargs is None


def test_inactive_tenant_is_skipped(env):
    env.mp.setattr(worker, "tenant_contexts", lambda: [(1, "other")])
    assert _call()["reason"] == "tenant_not_active"


def test_existing_tenant_connector_blocks_global_credentials(env):
    from app.models import IBKRConnection as Conn
    with env.admin_factory() as s:
        s.add(Conn(tenant_id=7, token_ciphertext="x", query_id="1", account_id="U1"))
        s.commit()
    out = _call()
    assert out == {"actor": "sync_ibkr_flex", "status": "skipped", "reason": "tenant_connector"}
    assert env.import_kwargs is None


def test_success_imports_for_the_owner_account_and_summarises(env):
    out = _call()
    assert out["status"] == "ok" and out["positions_imported"] == 3 and out["trades_imported"] == 5
    assert out["row_errors"] == 1  # cuenta, no el detalle
    assert env.import_kwargs["expected_account_id"] == "U123"  # trim
    assert env.import_kwargs["reconcile"] is True
    assert env.import_kwargs["query_complete_attested"] is True
    env.db.close.assert_called()


def test_complete_query_attestation_requires_same_query_id(env):
    env.settings.ibkr_flex_complete_query_id = "OTHER"
    _call()
    assert env.import_kwargs["query_complete_attested"] is False
    env.settings.ibkr_flex_complete_query_id = None
    _call()
    assert env.import_kwargs["query_complete_attested"] is False


def test_pnl_not_ready_retries_in_one_hour_and_rolls_back(env):
    env.import_error = import_module.IBKRPnlNotReadyError("PyG no listo")
    with pytest.raises(dramatiq.Retry) as exc:
        _call()
    assert exc.value.delay == 3_600_000
    assert env.rolled == [env.db]
    env.db.close.assert_called()


def test_import_error_is_a_structured_failure_without_retry(env):
    env.import_error = import_module.IBKRImportError("cuenta distinta")
    out = _call()
    assert out["status"] == "error" and out["error"]["type"] == "IBKRImportError"
    assert env.rolled == [env.db]


def test_unexpected_error_rolls_back_and_goes_through_error_policy(env):
    env.import_error = ValueError("boom")
    out = _call()
    assert out["status"] == "error" and out["error"]["message"] == "boom"
    assert env.rolled == [env.db]


def test_download_failure_never_opens_a_db_session(env):
    env.fetch_error = ibkr_module.IBKRFlexError("IBKR Flex HTTP 401")
    out = _call()
    assert out["status"] == "error" and "401" in out["error"]["message"]
    env.db.close.assert_not_called()
    assert env.import_kwargs is None
