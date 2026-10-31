"""El sync diario por tenant reintenta (acotado) cuando IBKR aun no tiene la PyG.

Sin reintento, un cron que corre antes del batch nocturno de IBKR falla con
not_ready y espera 24 h para fallar a la misma hora: bucle permanente. El
flujo global sync_ibkr_flex ya reintenta cada hora (max 2); el conector por
tenant debe comportarse igual. Solo not_ready reintenta: el resto de causas
son permanentes o no las arregla la espera.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock

import dramatiq
import pytest

from app.services import ibkr_connection_service as service
from app.workers import dramatiq_app as worker

RETRY_DELAY_MS = 3_600_000


def _drive(monkeypatch, download_exc=None, busy=False):
    """Ejecuta el actor del tenant con la capa IBKR sustituida.

    Devuelve (resultado_o_excepcion, record_failure_mock).
    """
    db = MagicMock()

    @contextmanager
    def fake_session(tenant_id, user_id):
        yield db

    monkeypatch.setattr(worker, "_session", fake_session)
    if busy:
        @contextmanager
        def busy_lease(db):
            raise service.SyncBusy("ocupado")
            yield
        monkeypatch.setattr(service, "sync_lease", busy_lease)
    else:
        @contextmanager
        def free_lease(db):
            yield
        monkeypatch.setattr(service, "sync_lease", free_lease)
        monkeypatch.setattr(service, "credentials",
                            lambda db, settings: ("token", "query", "U123456", 1))
        monkeypatch.setattr(service, "start_receipt", lambda db, **kw: 1)
        async def failing_download(token, query_id):
            raise download_exc
        monkeypatch.setattr(service, "download", failing_download)
    record_failure = MagicMock()
    monkeypatch.setattr(service, "record_failure", record_failure)
    return db, record_failure


def test_not_ready_records_receipt_and_retries_one_hour_later(monkeypatch):
    db, record_failure = _drive(monkeypatch, download_exc=service.SyncError("not_ready", "PyG pendiente"))
    with pytest.raises(dramatiq.Retry) as excinfo:
        worker.sync_one_tenant_ibkr.fn(2, "user")
    assert excinfo.value.delay == RETRY_DELAY_MS
    record_failure.assert_called_once()
    assert record_failure.call_args.kwargs["error_code"] == "not_ready"


def test_permanent_kind_records_receipt_without_retry(monkeypatch):
    db, record_failure = _drive(monkeypatch, download_exc=service.SyncError("credentials", "sin token"))
    result = worker.sync_one_tenant_ibkr.fn(2, "user")
    assert result["status"] == "error"
    assert record_failure.call_args.kwargs["error_code"] == "credentials"


def test_timeout_kind_records_receipt_without_retry(monkeypatch):
    # timeout es transitorio pero reintentar en caliente martillea a IBKR:
    # se registra y el proximo intento es el cron de manana.
    db, record_failure = _drive(monkeypatch, download_exc=service.SyncError("timeout", "90s"))
    result = worker.sync_one_tenant_ibkr.fn(2, "user")
    assert result["status"] == "error"
    assert record_failure.call_args.kwargs["error_code"] == "timeout"


def test_busy_lease_never_retries(monkeypatch):
    db, record_failure = _drive(monkeypatch, busy=True)
    result = worker.sync_one_tenant_ibkr.fn(2, "user")
    assert result["status"] == "busy"
    record_failure.assert_not_called()


def test_both_tenant_actors_allow_two_retries():
    assert worker.sync_one_tenant_ibkr.options["max_retries"] == 2
    assert worker.sync_one_tenant_ibkr_dedicated.options["max_retries"] == 2
