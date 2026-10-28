"""Encrypted tenant Flex connections. Never calls trading endpoints."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime
from functools import wraps
from threading import Lock
from typing import Concatenate, ParamSpec, TypeVar
from xml.etree import ElementTree

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.llm_settings_crypto import decrypt_api_key, encrypt_api_key
from app.models import IBKRConnection, IBKRSyncReceipt
from app.services.connectors.ibkr import IBKRFlexClient
from app.services.ibkr_import_service import (
    IBKRImportError,
    IBKRImportService,
    _statement_identity_blockers,
    validate_flex_xml,
)


class ConnectionError(ValueError):
    """Only fixed safe messages, no upstream payloads or credentials."""


class SyncBusy(ConnectionError):
    """Another manual or scheduled sync already owns this tenant."""


# SQLite is test/dev only. Production exclusion is PostgreSQL session-scoped,
# on a dedicated connection: importer commits cannot accidentally release it.
_LOCAL_LOCKS: dict[int, Lock] = {}
_LOCAL_LOCKS_GUARD = Lock()
_LOCK_NAMESPACE = 0x49424B52


@contextmanager
def sync_lease(db: Session):
    tenant_id = require_tenant(db)
    engine = db.get_bind()
    if engine.dialect.name == "sqlite":
        with _LOCAL_LOCKS_GUARD:
            lock = _LOCAL_LOCKS.setdefault(tenant_id, Lock())
        if not lock.acquire(blocking=False):
            raise SyncBusy("Ya hay una sincronización IBKR en curso.")
        try:
            yield
        finally:
            lock.release()
        return
    if engine.dialect.name != "postgresql":
        raise ConnectionError("La sincronización necesita PostgreSQL.")
    with engine.connect() as lease:
        acquired = lease.scalar(text("SELECT pg_try_advisory_lock(:ns, :tenant)"),
                                {"ns": _LOCK_NAMESPACE, "tenant": tenant_id})
        lease.commit()
        if not acquired:
            raise SyncBusy("Ya hay una sincronización IBKR en curso.")
        try:
            yield
        finally:
            try:
                lease.execute(text("SELECT pg_advisory_unlock(:ns, :tenant)"),
                              {"ns": _LOCK_NAMESPACE, "tenant": tenant_id})
                lease.commit()
            except BaseException:
                # Never return a pooled connection still owning a session lock.
                lease.invalidate()
                raise


_P = ParamSpec("_P")
_R = TypeVar("_R")


def _connection_mutation(fn: Callable[Concatenate[Session, _P], _R]) -> Callable[Concatenate[Session, _P], _R]:
    """Serialize credential changes with sync across importer commit boundaries.

    Reject rather than wait: the caller can retry when the sync completes. The
    separate session advisory lease survives every commit on the ORM session.
    Acquire before any row lock to keep the lock order identical to sync.
    """
    @wraps(fn)
    def guarded(db: Session, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with sync_lease(db):
            return fn(db, *args, **kwargs)
    return guarded


def start_receipt(db: Session, *, revision: int) -> int:
    receipt = IBKRSyncReceipt(tenant_id=require_tenant(db), revision=revision,
                              started_at=datetime.now(UTC), result="running", counts={})
    db.add(receipt)
    db.flush()
    receipt_id = receipt.id
    db.commit()
    return receipt_id


def _receipt_view(row: IBKRSyncReceipt | None) -> dict | None:
    if row is None:
        return None
    return {key: getattr(row, key) for key in (
        "id", "revision", "started_at", "finished_at", "period_start", "period_end",
        "result", "counts", "error_code",
    )}


# Only fixed numeric fields leave the importer. Row errors can contain raw XML
# attribute values, so store counts, never the messages or unknown attributes.
_COUNT_KEYS = (
    "positions_imported", "cash_imported", "trades_imported", "dividends_imported",
    "fees_imported", "cash_transactions_imported", "raw_rows_stored",
    "raw_rows_already_present", "rows_skipped", "fx_conversions_imported",
    "fx_conversions_skipped", "valuation_hold_kept",
)


def require_tenant(db: Session) -> int:
    tenant_id = db.info.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ConnectionError("Inicia sesión para configurar IBKR.")
    return tenant_id


def connection(db: Session, *, lock: bool = False) -> IBKRConnection | None:
    query = select(IBKRConnection).where(IBKRConnection.tenant_id == require_tenant(db))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def view(db: Session) -> dict:
    row = connection(db)
    latest = db.scalar(select(IBKRSyncReceipt).where(
        IBKRSyncReceipt.tenant_id == require_tenant(db),
    ).order_by(IBKRSyncReceipt.id.desc()).limit(1))
    return {
        "last_sync": _receipt_view(latest),
        "connected": bool(row and row.enabled and row.token_ciphertext),
        "account_id": row.account_id if row else None,
        "query_id": row.query_id if row and row.enabled else None,
        "status": row.status if row else "not_connected",
        "message": row.message if row else "Conecta una cuenta IBKR mediante Flex, solo lectura.",
        "last_attempt_at": row.last_attempt_at if row else None,
        "last_success_at": row.last_success_at if row else None,
        "statement_date": row.statement_date if row else None,
        "complete_query": row.complete_query if row else False,
    }


def validate_input(token: str, query_id: str, account_id: str) -> tuple[str, str, str]:
    token, query_id, account_id = token.strip(), query_id.strip(), account_id.strip().upper()
    if not re.fullmatch(r"[0-9]{8,128}", token):
        raise ConnectionError("Revisa el token Flex: debe contener solo números.")
    if not re.fullmatch(r"[0-9]{1,32}", query_id):
        raise ConnectionError("Revisa el Query ID de tu consulta Flex.")
    if not re.fullmatch(r"[A-Z][A-Z0-9]{2,63}", account_id):
        raise ConnectionError("Introduce la cuenta IBKR tal como figura en el extracto.")
    return token, query_id, account_id


def check_report(xml: str, account_id: str) -> date:
    # Strict gate: unlike manual imports this automatic path never partially
    # imports malformed rows or combines cash/positions from different dates.
    if len(xml) > 20_000_000:
        raise ConnectionError("El extracto es demasiado grande. Reduce el período de la consulta Flex.")
    if validate_flex_xml(xml):
        raise ConnectionError("El extracto Flex está incompleto o IBKR aún prepara los costes. Revisa la consulta y vuelve a intentarlo más tarde.")
    root = ElementTree.fromstring(xml)
    if _statement_identity_blockers(root, expected_account_id=account_id, max_age_days=5):
        raise ConnectionError("La cuenta o la fecha del extracto no coincide. Selecciona una sola cuenta y un extracto reciente en IBKR.")
    statement = next(e for e in root.iter() if e.tag.rsplit('}', 1)[-1] == "FlexStatement")
    report_date = date.fromisoformat(statement.attrib["toDate"].split(';', 1)[0]) if '-' in statement.attrib["toDate"] else datetime.strptime(statement.attrib["toDate"].split(';', 1)[0], "%Y%m%d").date()
    tags = {e.tag.rsplit('}', 1)[-1] for e in statement.iter()}
    if not {"OpenPositions", "CashReport"}.issubset(tags):
        raise ConnectionError("La consulta debe incluir Open Positions y Cash Report, también cuando estén vacíos.")
    for element in statement.iter():
        if element.tag.rsplit('}', 1)[-1] not in {"OpenPosition", "CashReportCurrency", "CashReport"}:
            continue
        if element.tag.rsplit('}', 1)[-1] == "CashReport" and "currency" not in element.attrib:
            continue
        raw = element.attrib.get("reportDate") or element.attrib.get("asOfDate") or element.attrib.get("toDate")
        if not raw:
            raise ConnectionError("Incluye la fecha del informe en posiciones y caja para no mezclar fechas.")
        value = raw.split(';', 1)[0]
        if value not in {report_date.isoformat(), report_date.strftime("%Y%m%d")}:
            raise ConnectionError("Las posiciones y la caja tienen fechas distintas. Revisa la consulta Flex.")
    return report_date


async def download(token: str, query_id: str) -> str:
    try:
        return await asyncio.wait_for(IBKRFlexClient(token=token, query_id=query_id).fetch_latest_xml(), timeout=90)
    except Exception:
        # No upstream exception reaches HTTP logs/error payloads here.
        raise ConnectionError("IBKR no pudo entregar el informe. Revisa token, caducidad, Query ID y restricciones de IP; si está preparándolo, prueba más tarde.") from None


@_connection_mutation
def save_connection(db: Session, settings: Settings, *, token: str, query_id: str,
                    account_id: str, complete_query: bool, statement_date: date) -> dict:
    tenant_id = require_tenant(db)
    token, query_id, account_id = validate_input(token, query_id, account_id)
    row = connection(db, lock=True)
    if row and row.account_id != account_id:
        raise ConnectionError("Esta cartera ya está vinculada a otra cuenta IBKR. No se pueden mezclar cuentas en esta versión.")
    # Keep the high-water mark even when credentials were disconnected. A
    # renewed token/query must never make an older report eligible for import.
    if row and row.statement_date and statement_date < row.statement_date:
        raise ConnectionError("El extracto es anterior al último verificado. Conservamos los datos más recientes.")
    # Preserve the existing owner-only legacy source account, never switch it.
    if settings.ibkr_flex_tenant_id == tenant_id and settings.ibkr_flex_account_id and settings.ibkr_flex_account_id.upper() != account_id:
        raise ConnectionError("La cuenta no coincide con la fuente IBKR existente de esta cartera.")
    ciphertext = encrypt_api_key(token, settings)
    if row is None:
        row = IBKRConnection(tenant_id=tenant_id, account_id=account_id, query_id=query_id)
        db.add(row)
    row.token_ciphertext = ciphertext
    row.query_id = query_id
    row.revision = (row.revision or 0) + 1
    row.enabled = True
    row.complete_query = complete_query
    row.status = "connected"
    row.message = "Conexión verificada. Pulsa Sincronizar para importar posiciones y caja."
    row.statement_date = statement_date
    db.commit()
    return view(db)


@_connection_mutation
def disconnect(db: Session) -> dict:
    row = connection(db, lock=True)
    if row:
        row.enabled = False
        row.token_ciphertext = None
        row.revision += 1
        row.status = "disconnected"
        row.message = "Desconectado. Se han conservado las posiciones y operaciones importadas."
        db.commit()
    return view(db)


def credentials(db: Session, settings: Settings) -> tuple[str, str, str, int]:
    row = connection(db)
    if not row or not row.enabled or not row.token_ciphertext:
        raise ConnectionError("Conecta IBKR antes de sincronizar.")
    result = (decrypt_api_key(row.token_ciphertext, settings), row.query_id, row.account_id, row.revision)
    # Do not hold a DB transaction across report generation.
    db.commit()
    return result


def import_report(db: Session, xml: str, account_id: str, revision: int, *, receipt_id: int | None = None) -> dict:
    report_date = check_report(xml, account_id)
    row = connection(db, lock=True)
    if not row or not row.enabled or row.revision != revision:
        raise ConnectionError("La conexión cambió durante la descarga. No se ha importado nada.")
    if row.statement_date and report_date < row.statement_date:
        raise ConnectionError("El extracto es anterior al último verificado. Conservamos los datos más recientes.")
    if receipt_id is None:
        receipt_id = start_receipt(db, revision=revision)
        row = connection(db, lock=True)
        if not row or not row.enabled or row.revision != revision:
            raise ConnectionError("La conexión cambió durante la descarga. No se ha importado nada.")
        if row.statement_date and report_date < row.statement_date:
            raise ConnectionError("El extracto es anterior al último verificado. Conservamos los datos más recientes.")
    receipt = db.scalar(select(IBKRSyncReceipt).where(IBKRSyncReceipt.id == receipt_id))
    if not receipt or receipt.revision != revision or receipt.result != "running":
        raise ConnectionError("El intento de sincronización ya no es válido.")
    statement = next(e for e in ElementTree.fromstring(xml).iter()
                     if e.tag.rsplit('}', 1)[-1] == "FlexStatement")
    raw_start = statement.attrib.get("fromDate", "").split(';', 1)[0]
    try:
        receipt.period_start = date.fromisoformat(raw_start)
    except ValueError:
        receipt.period_start = None
    receipt.period_end = report_date
    # Period is flushed with the import; final result is saved after its commit.
    db.flush()
    row.last_attempt_at = datetime.now(UTC)
    try:
        result = IBKRImportService().import_flex_xml(
            db, xml, expected_account_id=account_id,
            reconcile=row.complete_query, query_complete_attested=row.complete_query,
        )
    except IBKRImportError:
        db.rollback()
        raise ConnectionError("No se ha podido importar el extracto. Revisa la consulta Flex.") from None
    partial = bool(not row.complete_query or result.get("row_errors") or result.get("rows_skipped") or result.get("reconcile_blocked"))
    receipt = db.scalar(select(IBKRSyncReceipt).where(IBKRSyncReceipt.id == receipt_id))
    receipt.result = "partial" if partial else "synced"
    receipt.finished_at = datetime.now(UTC)
    receipt.counts = {key: result[key] for key in _COUNT_KEYS if type(result.get(key)) is int}
    receipt.counts["row_errors"] = len(result.get("row_errors") or [])
    receipt.counts["reconcile_blocked"] = len(result.get("reconcile_blocked") or [])
    row = connection(db, lock=True)
    if row and row.enabled and row.revision == revision:
        row.last_success_at = datetime.now(UTC)
        row.statement_date = report_date
        row.status = "partial" if partial else "synced"
        row.message = "Datos actualizados sin cerrar posiciones ausentes. Confirma una consulta completa para reconciliar la cartera." if not row.complete_query else "Importación parcial: revisa la consulta antes de dar la cartera por completa." if partial else "Posiciones y caja sincronizadas con el extracto de IBKR."
    db.commit()
    return view(db)


def record_failure(db: Session, *, revision: int | None, receipt_id: int | None = None) -> None:
    """Only the connection revision that started the failed request may change.

    No credentials obtained means no report request was attributed to a revision.
    Roll back its read transaction without changing a possibly renewed connection.
    """
    db.rollback()
    if revision is None:
        return
    if receipt_id is not None:
        receipt = db.scalar(select(IBKRSyncReceipt).where(IBKRSyncReceipt.id == receipt_id))
        if receipt and receipt.revision == revision and receipt.result == "running":
            receipt.result = "error"
            receipt.error_code = "sync_failed"
            receipt.finished_at = datetime.now(UTC)
    row = connection(db, lock=True)
    if row and row.enabled and row.revision == revision:
        row.last_attempt_at = datetime.now(UTC)
        row.status = "error"
        row.message = "No se pudo sincronizar. Conservamos los datos anteriores; revisa la conexión y vuelve a intentarlo."
    db.commit()
