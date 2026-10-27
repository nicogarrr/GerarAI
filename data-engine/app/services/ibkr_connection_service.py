"""Encrypted tenant Flex connections. Never calls trading endpoints."""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.llm_settings_crypto import decrypt_api_key, encrypt_api_key
from app.models import IBKRConnection
from app.services.connectors.ibkr import IBKRFlexClient
from app.services.ibkr_import_service import (
    IBKRImportError,
    IBKRImportService,
    _statement_identity_blockers,
    validate_flex_xml,
)


class ConnectionError(ValueError):
    """Only fixed safe messages, no upstream payloads or credentials."""


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
    return {
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


def save_connection(db: Session, settings: Settings, *, token: str, query_id: str,
                    account_id: str, complete_query: bool, statement_date: date) -> dict:
    tenant_id = require_tenant(db)
    token, query_id, account_id = validate_input(token, query_id, account_id)
    row = connection(db, lock=True)
    if row and row.account_id != account_id:
        raise ConnectionError("Esta cartera ya está vinculada a otra cuenta IBKR. No se pueden mezclar cuentas en esta versión.")
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


def import_report(db: Session, xml: str, account_id: str, revision: int) -> dict:
    report_date = check_report(xml, account_id)
    row = connection(db, lock=True)
    if not row or not row.enabled or row.revision != revision:
        raise ConnectionError("La conexión cambió durante la descarga. No se ha importado nada.")
    if row.statement_date and report_date < row.statement_date:
        raise ConnectionError("El extracto es anterior al último verificado. Conservamos los datos más recientes.")
    row.last_attempt_at = datetime.now(UTC)
    try:
        result = IBKRImportService().import_flex_xml(
            db, xml, expected_account_id=account_id,
            reconcile=row.complete_query, query_complete_attested=row.complete_query,
        )
    except IBKRImportError:
        db.rollback()
        raise ConnectionError("No se ha podido importar el extracto. Revisa la consulta Flex.") from None
    row = connection(db, lock=True)
    if row and row.enabled and row.revision == revision:
        row.last_success_at = datetime.now(UTC)
        row.statement_date = report_date
        partial = bool(not row.complete_query or result.get("row_errors") or result.get("rows_skipped") or result.get("reconcile_blocked"))
        row.status = "partial" if partial else "synced"
        row.message = "Datos actualizados sin cerrar posiciones ausentes. Confirma una consulta completa para reconciliar la cartera." if not row.complete_query else "Importación parcial: revisa la consulta antes de dar la cartera por completa." if partial else "Posiciones y caja sincronizadas con el extracto de IBKR."
        db.commit()
    return view(db)


def record_failure(db: Session) -> None:
    db.rollback()
    row = connection(db, lock=True)
    if row and row.enabled:
        row.last_attempt_at = datetime.now(UTC)
        row.status = "error"
        row.message = "No se pudo sincronizar. Conservamos los datos anteriores; revisa la conexión y vuelve a intentarlo."
        db.commit()
