"""Receipts de fallo con tipo de causa corto (sin mensajes ni datos sensibles)."""
import asyncio

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import IBKRSyncReceipt
from app.services import ibkr_connection_service as service
from app.services.connectors.ibkr import IBKRFlexError
from app.services.ibkr_import_service import _PNL_NOT_READY_MESSAGE, IBKRImportError, IBKRPnlNotReadyError
from tests.test_ibkr_tenant_connection import report, save, settings, tenant


def _download_kind(monkeypatch, raised):
    class _Client:
        def __init__(self, token: str, query_id: str) -> None:
            pass

        async def fetch_latest_xml(self) -> str:
            raise raised

    monkeypatch.setattr(service, "IBKRFlexClient", _Client)
    with pytest.raises(service.SyncError) as excinfo:
        asyncio.run(service.download("token", "query"))
    return excinfo.value.kind


def test_download_timeout_is_classified(monkeypatch):
    assert _download_kind(monkeypatch, TimeoutError()) == "timeout"


def test_download_ibkr_rejection_is_classified(monkeypatch):
    assert _download_kind(monkeypatch, IBKRFlexError("code 1012")) == "ibkr_rejected"


def test_download_network_error_is_unavailable(monkeypatch):
    assert _download_kind(monkeypatch, OSError("dns")) == "unavailable"


def test_credentials_failure_is_classified():
    init_db()
    with SessionLocal() as db:
        tenant(db)  # sin conexion guardada
        with pytest.raises(service.SyncError) as excinfo:
            service.credentials(db, settings())
        assert excinfo.value.kind == "credentials"


def test_check_report_wrong_account_is_report_kind():
    with pytest.raises(service.SyncError) as excinfo:
        service.check_report(report(account="U123456"), "U999999")
    assert excinfo.value.kind == "report"


def test_check_report_pnl_not_ready_is_its_own_kind(monkeypatch):
    monkeypatch.setattr(service, "validate_flex_xml", lambda xml: [_PNL_NOT_READY_MESSAGE])
    with pytest.raises(service.SyncError) as excinfo:
        service.check_report(report(), "U123456")
    assert excinfo.value.kind == "not_ready"


def test_import_report_revision_change_is_connection_changed():
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        stale_revision = service.connection(db).revision
        save(db)  # nueva revision: la que empezo la descarga ya no manda
        with pytest.raises(service.SyncError) as excinfo:
            service.import_report(db, report(), "U123456", stale_revision)
        assert excinfo.value.kind == "connection_changed"


def _import_kind(monkeypatch, raised):
    class _Importer:
        def import_flex_xml(self, *args, **kwargs):
            raise raised

    monkeypatch.setattr(service, "IBKRImportService", _Importer)
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        revision = service.connection(db).revision
        with pytest.raises(service.SyncError) as excinfo:
            service.import_report(db, report(), "U123456", revision)
        return excinfo.value.kind


def test_import_error_is_import_kind(monkeypatch):
    assert _import_kind(monkeypatch, IBKRImportError("fila mala")) == "import"


def test_pnl_not_ready_during_import_is_not_ready_kind(monkeypatch):
    assert _import_kind(monkeypatch, IBKRPnlNotReadyError("pnl")) == "not_ready"


def test_record_failure_persists_kind_and_falls_back_to_sync_failed():
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        revision = service.connection(db).revision
        first = service.start_receipt(db, revision=revision, origin="scheduled")
        service.record_failure(db, revision=revision, receipt_id=first,
                               error_code=service.error_kind(service.SyncError("timeout", "x")))
        second = service.start_receipt(db, revision=revision, origin="scheduled")
        service.record_failure(db, revision=revision, receipt_id=second,
                               error_code=service.error_kind(RuntimeError("que es esto")))
        rows = db.scalars(select(IBKRSyncReceipt).order_by(IBKRSyncReceipt.id)).all()
        assert [row.error_code for row in rows] == ["timeout", "sync_failed"]
        assert all(row.result == "error" for row in rows)
        assert [row.counts["origin"] for row in rows] == ["scheduled", "scheduled"]
        # Sin mensajes ni datos del fallo: solo el tipo corto.
        assert "que es esto" not in str(service.view(db))


def test_record_failure_rejects_unknown_error_code():
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        revision = service.connection(db).revision
        receipt_id = service.start_receipt(db, revision=revision)
        service.record_failure(db, revision=revision, receipt_id=receipt_id,
                               error_code="texto libre con detalles")
        assert db.scalar(select(IBKRSyncReceipt)).error_code == "sync_failed"


def test_successful_import_keeps_origin_in_counts(monkeypatch):
    class _Importer:
        def import_flex_xml(self, *args, **kwargs):
            return {"status": "ok", "positions_imported": 1, "row_errors": [],
                    "rows_skipped": 0, "reconcile_blocked": []}

    monkeypatch.setattr(service, "IBKRImportService", _Importer)
    init_db()
    with SessionLocal() as db:
        tenant(db)
        save(db)
        revision = service.connection(db).revision
        view = service.import_report(db, report(), "U123456", revision)
        counts = view["last_sync"]["counts"]
        assert counts["origin"] == "manual"  # import_report directo = flujo manual
        assert counts["positions_imported"] == 1
