from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CashBalance, Company, Position, Transaction
from app.services.number_parsing import parse_localized_number
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_ledger_service import PortfolioLedgerService


class IBKRImportError(ValueError):
    """Fichero IBKR inválido: mensaje accionable en español."""


class IBKRPnlNotReadyError(IBKRImportError):
    """IBKR genero el informe antes de tener disponible su PyG."""


_PNL_NOT_READY_MESSAGE = (
    "IBKR todavia no ha preparado la PyG de este informe. "
    "No se ha importado: se conserva la cartera anterior. "
    "Vuelve a descargarlo cuando IBKR lo regenere."
)


def _is_number(value: str | None) -> bool:
    if value in (None, ""):
        return False
    return parse_localized_number(value) is not None


def _is_date(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.split(";", 1)[0].split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            datetime.strptime(normalized, fmt)
            return True
        except ValueError:
            continue
    return False


def validate_flex_xml(xml_text: str) -> list[str]:
    """Valida un Flex Query XML de IBKR.

    Devuelve una lista de errores accionables en español
    (``fila N (TAG …): qué falla y cómo arreglarlo``).
    Lista vacía = fichero válido. No toca la base de datos.
    """
    errors: list[str] = []
    if not xml_text or not xml_text.strip():
        return ["El fichero está vacío: descarga de nuevo el Flex Query XML desde IBKR (Informes > Flex Queries)."]
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        return [
            f"El XML no se puede leer ({exc}): el fichero está incompleto o no es XML. "
            "Descarga de nuevo el Flex Query completo desde IBKR sin abrirlo ni editarlo."
        ]
    if _tag_name(root) != "FlexQueryResponse":
        # Aceptamos cualquier raíz que contenga statements; si no hay
        # ninguna etiqueta conocida, no es un Flex Query.
        tags = {_tag_name(el) for el in root.iter()}
        if not tags & {"OpenPosition", "Trade", "CashTransaction", "CashReport", "CorporateAction", "FlexStatement"}:
            return [
                f"La raíz <{_tag_name(root)}> no parece un Flex Query de IBKR: no contiene "
                "OpenPosition, Trade, CashTransaction ni CashReport. Revisa que el fichero "
                "sea el XML del Flex Query (no el CSV ni un extracto parcial)."
            ]
    # IBKR can return a successful XML with real quantities but placeholder
    # zero costs. Reject the whole snapshot before any write or reconciliation.
    for element in root.iter():
        if _tag_name(element) == "Message":
            message = " ".join(" ".join(element.itertext()).lower().split())
            if "realized p/l is not ready" in message and "disabled" in message:
                return [_PNL_NOT_READY_MESSAGE]
    for index, element in enumerate(root.iter(), start=1):
        tag = _tag_name(element)
        if tag == "OpenPosition":
            symbol = _attr(element, "symbol", "underlyingSymbol")
            if not symbol:
                errors.append(
                    f"Fila {index} (OpenPosition): falta el símbolo (atributo symbol). "
                    "Esa posición se omite; revisa la query en IBKR para que incluya la columna Symbol."
                )
            missing_fields = _missing_position_fields(element)
            if symbol and missing_fields:
                errors.append(
                    f"Fila {index} (OpenPosition {symbol}): faltan {', '.join(missing_fields)}. "
                    "Esa posición se omite para no crear ceros ni una fecha inventada; "
                    "incluye esas columnas en la Flex Query."
                )
            for attr in ("position", "quantity"):
                raw = _attr(element, attr)
                if raw is not None and not _is_number(raw):
                    errors.append(
                        f"Fila {index} (OpenPosition {symbol or '?'}): la cantidad '{raw}' "
                        f"(atributo {attr}) no es un número. Corrige el valor o excluye la fila."
                    )
                    break
            for attr in ("markPrice", "marketPrice", "price", "positionValue", "marketValue",
                         "costBasisPrice", "costPrice", "avgPrice"):
                raw = _attr(element, attr)
                if raw is not None and not _is_number(raw):
                    errors.append(
                        f"Fila {index} (OpenPosition {symbol or '?'}): el precio/valor '{raw}' "
                        f"(atributo {attr}) no es un número. Corrige el valor o excluye la fila."
                    )
                    break
        elif tag == "Trade":
            symbol = _attr(element, "symbol", "underlyingSymbol")
            if not symbol:
                errors.append(
                    f"Fila {index} (Trade): falta el símbolo (atributo symbol). "
                    "Esa operación se omite; revisa que la query incluya la columna Symbol."
                )
            raw_qty = _attr(element, "quantity", "shares")
            if raw_qty is not None and not _is_number(raw_qty):
                errors.append(
                    f"Fila {index} (Trade {symbol or '?'}): la cantidad '{raw_qty}' no es un número. "
                    "Corrige el valor o excluye la fila."
                )
            raw_price = _attr(element, "tradePrice", "price")
            if raw_price is not None and not _is_number(raw_price):
                errors.append(
                    f"Fila {index} (Trade {symbol or '?'}): el precio '{raw_price}' no es un número. "
                    "Corrige el valor o excluye la fila."
                )
            raw_date = _attr(element, "tradeDate", "dateTime", "date")
            if raw_date is not None and not _is_date(raw_date):
                errors.append(
                    f"Fila {index} (Trade {symbol or '?'}): la fecha '{raw_date}' no tiene un formato "
                    "reconocido (usa AAAA-MM-DD). Corrige el valor o excluye la fila."
                )
        elif tag == "CashTransaction":
            raw_amount = _attr(element, "amount", "netCash", "proceeds")
            if raw_amount is not None and not _is_number(raw_amount):
                errors.append(
                    f"Fila {index} (CashTransaction): el importe '{raw_amount}' no es un número. "
                    "Corrige el valor o excluye la fila."
                )
            raw_date = _attr(element, "dateTime", "date", "tradeDate")
            if raw_date is not None and not _is_date(raw_date):
                errors.append(
                    f"Fila {index} (CashTransaction): la fecha '{raw_date}' no tiene un formato "
                    "reconocido (usa AAAA-MM-DD). Corrige el valor o excluye la fila."
                )
        elif tag in ("CashReport", "CashReportCurrency"):
            if _is_cash_summary_row(element):
                continue
            if not _attr(element, "currency"):
                errors.append(
                    f"Fila {index} (CashReport): falta la divisa (atributo currency). "
                    "Ese saldo se omite; revisa que la query incluya la columna Currency."
                )
            raw_cash = _attr(element, "endingCash", "cash", "balance")
            if raw_cash is not None and not _is_number(raw_cash):
                errors.append(
                    f"Fila {index} (CashReport): el saldo '{raw_cash}' no es un número. "
                    "Corrige el valor o excluye la fila."
                )
    return errors


# Columnas aceptadas (minúsculas) para el CSV de actividad de IBKR.
_CSV_REQUIRED_COLUMNS = ("symbol", "action", "quantity", "price", "date")
_CSV_COLUMN_ALIASES = {
    "external_id": ("tradeid", "transactionid", "ibexecid", "external_id"),
    "symbol": {"symbol", "ticker", "underlyingsymbol"},
    "action": {"action", "buysell", "transactiontype", "type", "side"},
    "quantity": {"quantity", "shares", "position"},
    "price": {"price", "tradeprice", "avgprice"},
    "date": {"date", "tradedate", "datetime"},
    "fees": {"fees", "commission", "ibcommission"},
    "currency": {"currency", "currencyprimary"},
}


def _normalize_csv_header(cell: str) -> str:
    """Nombre de columna comparable con los alias.

    Sin BOM (Excel «CSV UTF-8»), en minusculas y solo letras, digitos y ``_``:
    la Flex Query de IBKR exporta «Buy/Sell» y debe casar con ``buysell``.
    """
    return re.sub(r"[^a-z0-9_]", "", cell.replace("\ufeff", "").strip().lower())


def _map_csv_columns(header: list[str]) -> dict[str, int] | None:
    normalized = [_normalize_csv_header(cell) for cell in header]
    mapping: dict[str, int] = {}
    for canonical, aliases in _CSV_COLUMN_ALIASES.items():
        for position, cell in enumerate(normalized):
            if cell in aliases:
                mapping.setdefault(canonical, position)
                break
    if any(column not in mapping for column in _CSV_REQUIRED_COLUMNS):
        return None
    return mapping


def _csv_trade_action(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized in {"buy", "bot", "b"}:
        return "buy"
    if normalized in {"sell", "sold", "s"}:
        return "sell"
    return None


def _csv_delimiter(csv_text: str) -> str:
    """Separador del CSV, decidido por la CABECERA (no por las celdas).

    Excel/LibreOffice en español exportan «CSV» con «;» porque la coma es el
    decimal (12,50). Solo cuenta la primera línea con contenido, así una
    celda entrecomillada con «;» en un CSV de comas no cambia la lectura.
    """
    header = next((line for line in csv_text.splitlines() if line.strip()), "")
    return ";" if header.count(";") > header.count(",") else ","


def _csv_rows(csv_text: str) -> list[list[str]]:
    text = csv_text.strip()
    return list(csv.reader(io.StringIO(text), delimiter=_csv_delimiter(text)))


def validate_ibkr_csv(csv_text: str) -> list[str]:
    """Valida un CSV de actividad de IBKR (cabecera + filas).

    Devuelve errores accionables en español con número de fila.
    Lista vacía = fichero válido. No toca la base de datos.
    """
    if not csv_text or not csv_text.strip():
        return ["El fichero está vacío: exporta de nuevo la actividad desde IBKR en formato CSV."]
    try:
        rows = _csv_rows(csv_text)
    except csv.Error as exc:
        return [
            f"El CSV no se puede leer ({exc}): revisa que el fichero use comas como separador "
            "y que no esté corrupto."
        ]
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        return [
            "El CSV no contiene filas de datos: debe tener una fila de cabecera "
            "(symbol, action, quantity, price, date) y al menos una operación."
        ]
    mapping = _map_csv_columns(rows[0])
    if mapping is None:
        return [
            "La cabecera del CSV no tiene las columnas obligatorias: symbol, action, quantity, price y date "
            "(se aceptan alias como ticker, buySell, shares, tradePrice o tradeDate). "
            f"Cabecera encontrada: {', '.join(rows[0])}."
        ]
    errors: list[str] = []
    for line_number, row in enumerate(rows[1:], start=2):
        symbol = row[mapping["symbol"]].strip() if mapping["symbol"] < len(row) else ""
        if not symbol:
            errors.append(
                f"Fila {line_number} del CSV: falta el símbolo. Indica el ticker (p. ej. AAPL) o elimina la fila."
            )
            continue
        raw_action = row[mapping["action"]].strip() if mapping["action"] < len(row) else ""
        action = _csv_trade_action(raw_action)
        if not raw_action:
            errors.append(
                f"Fila {line_number} del CSV ({symbol}): falta la acción. Usa 'buy' o 'sell' "
                "o elimina la fila."
            )
        elif action is None:
            errors.append(
                f"Fila {line_number} del CSV ({symbol}): la acción '{raw_action}' no es buy ni sell. "
                "Corrige el valor o elimina la fila."
            )
        quantity = row[mapping["quantity"]].strip() if mapping["quantity"] < len(row) else ""
        if not _is_number(quantity):
            errors.append(
                f"Fila {line_number} del CSV ({symbol}): la cantidad '{quantity}' no es un número. "
                "Corrige el valor o elimina la fila."
            )
        price = row[mapping["price"]].strip() if mapping["price"] < len(row) else ""
        if not _is_number(price):
            errors.append(
                f"Fila {line_number} del CSV ({symbol}): el precio '{price}' no es un número. "
                "Corrige el valor o elimina la fila."
            )
        day = row[mapping["date"]].strip() if mapping["date"] < len(row) else ""
        if not _is_date(day):
            errors.append(
                f"Fila {line_number} del CSV ({symbol}): la fecha '{day}' no tiene un formato "
                "reconocido (usa AAAA-MM-DD). Corrige el valor o elimina la fila."
            )
    return errors


def _is_cash_summary_row(element: ElementTree.Element) -> bool:
    """Filas de efectivo que no son un saldo por divisa.

    El total en divisa base (BASE_SUMMARY) no es una divisa, y el contenedor
    <CashReport> del Flex real no lleva atributos: solo agrupa CashReportCurrency.
    """
    if not element.attrib and len(element) > 0:
        return True
    currency = (_attr(element, "currency") or "").upper()
    level = (_attr(element, "levelOfDetail") or "").lower()
    return currency == "BASE_SUMMARY" or level == "basecurrency"


def _tag_name(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


_MACHINE_DECIMAL = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def _decimal(value: str | None, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    # Los atributos del Flex XML son numeros de maquina: el punto es SIEMPRE el
    # decimal. parse_localized_number lee "32.725" como 32725 (agrupacion es-ES):
    # vendia ZETA a 32.725 US$ en vez de 32,725.
    plain = str(value).strip()
    if _MACHINE_DECIMAL.match(plain):
        return Decimal(plain)
    parsed = parse_localized_number(value)
    if parsed is None:
        # An unparseable amount must not become a silent 0: a zero cash flow is
        # a real fact, and coercing a corrupt one to zero writes a false entry
        # into the ledger and the tax report.
        raise IBKRImportError(
            f"Importe no interpretable: {value!r}. Usa notacion en-US (1,234.56) "
            "o es-ES (1.234,56)."
        )
    return parsed[0]


def _csv_decimal(value: str) -> Decimal:
    """Number from an IBKR CSV cell (en-US or es-ES notation).

    The old code stripped every comma, so "12,50" became 1250 and "1.234,56"
    became 1.23456. A cell without a comma that is a plain machine decimal
    ("100.25", "32.725") keeps the previous reading, so already imported rows
    keep their identity. A cell with a comma goes through the shared
    localized parser (same one the validation uses); "1,234" still reads as
    1234 and "1,5"/"12,50" as decimals. Not interpretable -> error, never 0.
    """
    plain = str(value).strip()
    if "," not in plain and _MACHINE_DECIMAL.match(plain):
        return Decimal(plain)
    parsed = parse_localized_number(plain)
    if parsed is None:
        raise IBKRImportError(
            f"Importe no interpretable: {value!r}. Usa notacion en-US (1,234.56) "
            "o es-ES (1.234,56)."
        )
    return parsed[0]


def _legacy_csv_values(symbol: str, action: str, cell) -> list[str] | None:
    """Fingerprint values exactly as the pre-_csv_decimal importer built them."""
    try:
        return [
            symbol,
            action,
            str(abs(Decimal(cell("quantity").replace(",", "")).normalize())),
            str(Decimal(cell("price").replace(",", "")).normalize()),
            _date(cell("date")).isoformat(),
            str(abs(Decimal(cell("fees").replace(",", "")).normalize())) if cell("fees") else "0",
            cell("currency").upper() or "USD",
        ]
    except Exception:  # noqa: BLE001 - unreadable legacy form: no legacy identity
        return None


def _missing_position_fields(element: ElementTree.Element) -> list[str]:
    """Economic fields an OpenPosition needs so nothing is invented (F377).

    A missing quantity, price/value or report date must not become 0 / today:
    that would overwrite a real position with zeros and a made-up date.
    """
    missing: list[str] = []
    if _attr(element, "position", "quantity") is None:
        missing.append("cantidad (position)")
    if _attr(element, "markPrice", "marketPrice", "price", "positionValue", "marketValue") is None:
        missing.append("precio o valor de mercado (markPrice/positionValue)")
    raw_date = _attr(element, "reportDate", "asOfDate")
    if raw_date is None or not _is_date(raw_date):
        missing.append("fecha del informe (reportDate)")
    return missing


def _date(value: str | None) -> date:
    if not value:
        return date.today()
    normalized = value.split(";", 1)[0].split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return date.today()


def _attr(element: ElementTree.Element, *names: str) -> str | None:
    lowered = {key.lower(): value for key, value in element.attrib.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _statement_identity_blockers(
    root: ElementTree.Element, *, expected_account_id: str, max_age_days: int
) -> list[str]:
    """Cuenta y fecha del extracto. Se evalua ANTES de escribir nada."""
    reasons: list[str] = []
    expected = expected_account_id.strip().upper()
    statements = [e for e in root.iter() if _tag_name(e) == "FlexStatement"]
    if len(statements) != 1:
        return [f"se esperaba 1 FlexStatement y hay {len(statements)}"]
    statement = statements[0]
    account = (statement.attrib.get("accountId") or "").strip().upper()
    if account != expected:
        reasons.append("la cuenta del extracto no es la esperada")
    raw_to = (statement.attrib.get("toDate") or "").split(";", 1)[0].strip()
    to_date: date | None = None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            to_date = datetime.strptime(raw_to, fmt).date()
            break
        except ValueError:
            continue
    if to_date is None:
        reasons.append("el extracto no trae toDate valido")
    else:
        today = date.today()
        if to_date > today:
            reasons.append("toDate esta en el futuro")
        elif to_date < today - timedelta(days=max_age_days):
            reasons.append(f"el extracto es mas antiguo de {max_age_days} dias")
    # Cualquier fila con accountId (Trade, CashTransaction, CashReport, ...) debe ser
    # de la cuenta esperada: no entra nada de otra cuenta.
    for element in root.iter():
        row_account = (element.attrib.get("accountId") or "").strip().upper()
        if row_account and row_account != expected:
            reasons.append("hay filas de otra cuenta")
            break
    return reasons


def _snapshot_blockers(
    root: ElementTree.Element,
    *,
    expected_account_id: str,
    positions_imported: int,
    position_rows_skipped: int,
    cash_rows_skipped: int,
    cash_imported: int,
    max_age_days: int,
    query_complete_attested: bool,
) -> list[str]:
    """Motivos por los que el extracto NO prueba ser un snapshot completo de la cuenta."""
    reasons = _statement_identity_blockers(
        root, expected_account_id=expected_account_id, max_age_days=max_age_days
    )
    if not query_complete_attested:
        reasons.append(
            "la consulta Flex no esta declarada como completa (sin filtros, todas las secciones)"
        )
    statements = [e for e in root.iter() if _tag_name(e) == "FlexStatement"]
    if len(statements) != 1:
        return reasons
    statement = statements[0]
    raw_to = (statement.attrib.get("toDate") or "").split(";", 1)[0].strip()
    to_date: date | None = None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            to_date = datetime.strptime(raw_to, fmt).date()
            break
        except ValueError:
            continue
    tags = {_tag_name(e) for e in statement.iter()}
    if "OpenPositions" not in tags:
        reasons.append("falta la seccion OpenPositions")
    if "CashReport" not in tags:
        reasons.append("falta la seccion CashReport")
    if not positions_imported:
        reasons.append("el extracto no trae posiciones")
    if position_rows_skipped:
        reasons.append("hay filas de posición omitidas")
    if cash_rows_skipped:
        reasons.append("hay filas de caja omitidas")
    if not cash_imported:
        reasons.append("el extracto no trae saldos de caja")
    if to_date is not None:
        for element in statement.iter():
            if _tag_name(element) != "OpenPosition":
                continue
            raw = (element.attrib.get("reportDate") or "").split(";", 1)[0].strip()
            if raw and raw.replace("-", "") != to_date.strftime("%Y%m%d"):
                reasons.append("hay posiciones con fecha distinta al statement")
                break
    return reasons


def _is_cancel_trade(element: ElementTree.Element) -> bool:
    """Fila Flex que anula una operacion anterior: ``BUY (Ca.)``/``SELL (Ca.)`` o ``TradeCancel``."""
    side = (_attr(element, "buySell") or "").lower()
    kind = (_attr(element, "transactionType", "tradeType") or "").lower()
    return "(ca" in side or kind in {"tradecancel", "fracsharecancel"}


def _cancelled_side(element: ElementTree.Element) -> str | None:
    raw = (_attr(element, "buySell") or "").split("(", 1)[0]
    side = raw.strip().lower()
    if side in {"buy", "bot", "b"}:
        return "buy"
    if side in {"sell", "sold", "s"}:
        return "sell"
    return None


def _find_cancelled_trade(
    db: Session,
    element: ElementTree.Element,
    company: Company,
    file_trades: list[Transaction],
) -> Transaction | None:
    """Operacion original que anula ``element``, o None si no hay UNA sola candidata.

    Si la fila trae ``origTradeID`` se usa tal cual. Si no, deben coincidir empresa,
    sentido, cantidad absoluta, precio y ``ibOrderID`` (cuando ambos lo traen). Con cero
    o varias candidatas no se adivina: se devuelve None y la fila se omite para revision.
    """
    orig_id = _attr(element, "origTradeID")
    quantity = abs(_decimal(_attr(element, "quantity", "shares")))
    price = _decimal(_attr(element, "tradePrice", "price"))
    side = _cancelled_side(element)
    order_id = _attr(element, "ibOrderID")
    pool = [t for t in file_trades if t.company_id == company.id]
    pool += list(
        db.scalars(
            select(Transaction).where(
                Transaction.company_id == company.id,
                Transaction.action.in_(("buy", "sell")),
                *tenant_filters(db, Transaction),
            )
        ).all()
    )
    seen: set[int] = set()
    candidates: list[Transaction] = []
    for trade in pool:
        if id(trade) in seen or trade.action not in ("buy", "sell"):
            continue
        seen.add(id(trade))
        if orig_id and orig_id != "0":
            if trade.external_id == orig_id:
                candidates.append(trade)
            continue
        payload_order = (trade.raw_payload or {}).get("ibOrderID")
        if (
            trade.action == side
            and trade.quantity == quantity
            and trade.price == price
            and (not order_id or not payload_order or order_id == payload_order)
        ):
            candidates.append(trade)
    return candidates[0] if len(candidates) == 1 else None


def _auto_link_journal_after_import(db: Session) -> None:
    """Enlaza decisiones del diario con las operaciones recien importadas (inequivocas)."""
    from app.services.journal_trade_link import auto_link_journal_trades_best_effort

    auto_link_journal_trades_best_effort(db)


class IBKRImportService:
    def import_flex_xml(
        self,
        db: Session,
        xml_text: str,
        *,
        reconcile: bool = False,
        expected_account_id: str | None = None,
        reconcile_sources: tuple[str, ...] = ("ibkr_flex",),
        dry_run: bool = False,
        query_complete_attested: bool = False,
        max_statement_age_days: int = 5,
        trades_only: bool = False,
        only_existing_companies: bool = False,
        include_cash_income: bool = False,
    ) -> dict:
        """Importa un Flex Query.

        ``trades_only=True`` (backfill historico): solo se leen las filas ``Trade`` de
        acciones y se escriben como operaciones del libro (idempotente por trade id).
        No toca posiciones, caja, reconcile ni snapshots; con ``dry_run`` hace rollback.
        ``only_existing_companies=True`` omite (y lista) los simbolos sin Company, para no
        crear emisores nuevos. ``include_cash_income=True`` (solo con trades_only) importa
        tambien dividendos, retenciones, intereses y comisiones (CashTransaction) por su id;
        los depositos/retiradas y otros movimientos (cash_misc) se omiten porque alimentan
        el flujo de caja de los snapshots.

        ``reconcile=True`` hace IBKR fuente de verdad: tras importar un extracto
        completo se eliminan las posiciones y saldos de caja que ya no vienen en el
        (las operaciones del libro no se tocan). Solo actua si el extracto trae
        posiciones y ninguna se omitio; un extracto vacio o roto nunca vacia la cartera.

        Contrato de snapshot completo (sin el, se importa en modo merge y NO se borra
        nada; ``reconcile_blocked`` lista los motivos): ``expected_account_id``
        obligatorio, un unico FlexStatement de esa cuenta, ``toDate`` valido y no
        anterior a ``max_statement_age_days``, todas las filas de esa cuenta y con
        fecha del statement, secciones OpenPositions y CashReport presentes sin filas
        omitidas. Solo se borran filas cuyo ``source`` este en ``reconcile_sources``
        (por defecto ``ibkr_flex``) y solo si ``query_complete_attested`` (la consulta
        Flex esta declarada sin filtros y con todas las secciones; el XML no puede
        probarlo). Con ``expected_account_id`` una cuenta/fecha incorrecta se rechaza
        antes de escribir. Lo manual u otras fuentes no se tocan.
        ``dry_run=True`` calcula lo que cerraria y hace rollback de todo.
        """
        # Los errores de fila ("se omite…", "excluye la fila") no bloquean:
        # se importan las filas válidas y se devuelven en row_errors. Solo los
        # errores fatales (XML ilegible, raíz incorrecta) interrumpen.
        parse_errors = validate_flex_xml(xml_text)
        if _PNL_NOT_READY_MESSAGE in parse_errors:
            raise IBKRPnlNotReadyError(_PNL_NOT_READY_MESSAGE)
        fatal_errors = [
            error
            for error in parse_errors
            if "se omite" not in error and "excluye la fila" not in error
        ]
        if fatal_errors:
            raise IBKRImportError(" ".join(fatal_errors))
        row_errors = [error for error in parse_errors if error not in fatal_errors]
        root = ElementTree.fromstring(xml_text)
        if reconcile and not (expected_account_id or "").strip():
            raise IBKRImportError(
                "reconcile exige expected_account_id: sin cuenta esperada no se puede probar que el extracto es completo."
            )
        if expected_account_id and expected_account_id.strip():
            # Cuenta equivocada, varias cuentas o statement antiguo: se rechaza ANTES
            # de escribir nada (tambien en modo merge).
            identity = _statement_identity_blockers(
                root,
                expected_account_id=expected_account_id,
                max_age_days=max_statement_age_days,
            )
            if identity:
                raise IBKRImportError("Extracto Flex rechazado: " + "; ".join(identity) + ".")
        # Batch: all external ids referenced by this report, one existence query
        # instead of one per row.
        report_ids = {
            value
            for element in root.iter()
            for key, value in element.attrib.items()
            if key.lower()
            in {"tradeid", "transactionid", "ibexecid", "trxid", "id"}
            and value
        }
        existing_ids = (
            {
                row[0]
                for row in db.execute(
                    select(Transaction.external_id).where(
                        Transaction.external_id.in_(report_ids),
                        *tenant_filters(db, Transaction),
                    )
                ).all()
            }
            if report_ids
            else set()
        )
        fx_service = PortfolioFXService()
        portfolio = fx_service.ensure_portfolio(db)
        companies: dict[str, Company] = {}
        positions_imported = 0
        valuation_hold_kept: list[str] = []
        cash_imported = 0
        trades_imported = 0
        dividends_imported = 0
        fees_imported = 0
        cash_transactions_imported = 0
        rows_skipped = 0
        unattributed = 0
        imported_company_ids: set[int] = set()
        imported_cash_currencies: set[str] = set()
        position_rows_skipped = 0
        cash_rows_skipped = 0

        trades_already_present = 0
        non_stock_skipped = 0
        unknown_tickers: dict[str, int] = {}
        elements = list(root.iter())
        if trades_only:
            # Primero los Trade: crean los emisores a los que luego se atribuyen
            # los dividendos (orden estable, el resto mantiene su orden).
            elements.sort(key=lambda e: 0 if _tag_name(e) == "Trade" else 1)
        # Las anulaciones se procesan despues de todas las operaciones del extracto,
        # vengan en el orden que vengan, para poder neutralizar a su original.
        elements.sort(key=lambda e: 1 if _tag_name(e) == "Trade" and _is_cancel_trade(e) else 0)
        file_trades: list[Transaction] = []
        trades_cancelled = 0
        cash_misc_skipped = 0
        for element in elements:
            tag = _tag_name(element)
            if trades_only and tag != "Trade" and not (include_cash_income and tag == "CashTransaction"):
                continue
            if trades_only and tag == "Trade" and (_attr(element, "assetCategory") or "STK").upper() != "STK":
                # Divisas (EUR.USD), opciones, etc.: no son compras de acciones del libro.
                non_stock_skipped += 1
                continue
            if tag == "OpenPosition":
                symbol = _attr(element, "symbol", "underlyingSymbol")
                if not symbol:
                    rows_skipped += 1
                    position_rows_skipped += 1
                    continue
                if _missing_position_fields(element):
                    rows_skipped += 1
                    position_rows_skipped += 1
                    continue
                raw_quantity = _attr(element, "position", "quantity")
                raw_price = _attr(element, "markPrice", "marketPrice", "price")
                raw_value = _attr(element, "positionValue", "marketValue")
                raw_cost = _attr(element, "costBasisPrice", "costPrice", "avgPrice")
                if any(
                    raw is not None and not _is_number(raw)
                    for raw in (raw_quantity, raw_price, raw_value, raw_cost)
                ):
                    rows_skipped += 1
                    position_rows_skipped += 1
                    continue
                company = self._company(db, companies, symbol)
                self._capture_isin(company, element)
                quantity = _decimal(_attr(element, "position", "quantity"))
                market_price = _decimal(_attr(element, "markPrice", "marketPrice", "price"))
                market_value = _decimal(_attr(element, "positionValue", "marketValue"))
                if market_value == 0 and market_price and quantity:
                    market_value = quantity * market_price
                average_cost = _decimal(_attr(element, "costBasisPrice", "costPrice", "avgPrice"))
                position = db.scalar(select(Position).where(Position.company_id == company.id))
                if position is None:
                    position = Position(company_id=company.id, portfolio_id=portfolio.id)
                    db.add(position)
                position.quantity = quantity
                position.average_cost = average_cost
                position.market_price = market_price
                position.market_value = market_value
                position.unrealized_pnl = _decimal(_attr(element, "fifoPnlUnrealized", "unrealizedPnl"))
                position.currency = _attr(element, "currency") or company.currency
                position.portfolio_id = portfolio.id
                position.base_currency = portfolio.base_currency
                position.as_of = _date(_attr(element, "reportDate", "asOfDate"))
                position.market_value_native = market_value
                position.cost_basis_native = quantity * average_cost
                rate = fx_service.rate(
                    db,
                    quote_currency=position.currency,
                    base_currency=portfolio.base_currency,
                    as_of=position.as_of,
                )
                position.fx_rate = rate
                position.market_value_base = market_value * rate if rate is not None else None
                position.cost_basis_base = (
                    position.cost_basis_native * rate if rate is not None else None
                )
                position.unrealized_pnl_base = (
                    position.market_value_base - position.cost_basis_base
                    if position.market_value_base is not None
                    and position.cost_basis_base is not None
                    else None
                )
                position.source = "ibkr_flex"
                if position.valuation_hold_reason:
                    # El hold no se levanta por una importacion: cantidad y coste
                    # llegan del extracto, la valoracion sigue en suspension y se
                    # declara (el extracto no es un precio post-split verificado
                    # para esta via; liberar exige release_valuation_hold).
                    held_as_of = position.as_of
                    PortfolioLedgerService._blank_valuation(position)
                    position.as_of = held_as_of
                    valuation_hold_kept.append(symbol)
                imported_company_ids.add(company.id)
                positions_imported += 1

            elif tag in ("CashReport", "CashReportCurrency"):
                if _is_cash_summary_row(element):
                    continue
                currency = _attr(element, "currency")
                if not currency:
                    rows_skipped += 1
                    cash_rows_skipped += 1
                    continue
                raw_cash = _attr(element, "endingCash", "cash", "balance")
                if raw_cash is None or not _is_number(raw_cash):
                    # A missing amount is not zero: it would overwrite a real
                    # CashBalance with 0 (same rule as OpenPosition, F377).
                    rows_skipped += 1
                    cash_rows_skipped += 1
                    continue
                raw_cash_date = _attr(element, "reportDate", "asOfDate", "toDate")
                if raw_cash_date is None or not _is_date(raw_cash_date):
                    # A missing/invalid date is never "today": the row is skipped
                    # and the existing CashBalance (amount and as_of) is kept.
                    rows_skipped += 1
                    cash_rows_skipped += 1
                    continue
                cash = db.scalar(select(CashBalance).where(CashBalance.currency == currency))
                imported_cash_currencies.add(currency)
                if cash is None and abs(_decimal(_attr(element, "endingCash", "cash", "balance"))) < Decimal("0.005"):
                    # Polvo de redondeo (1e-5): no crea una divisa fantasma.
                    continue
                if cash is None:
                    cash = CashBalance(currency=currency)
                    db.add(cash)
                cash.balance = _decimal(_attr(element, "endingCash", "cash", "balance"))
                cash.settled_cash = _decimal(_attr(element, "settledCash", "endingSettledCash"), str(cash.balance))
                cash.interest_rate = _decimal(_attr(element, "interestRate"))
                cash.source = "ibkr_flex"
                cash.as_of = _date(_attr(element, "reportDate", "asOfDate", "toDate"))
                cash_imported += 1

            elif tag == "Trade":
                symbol = _attr(element, "symbol", "underlyingSymbol")
                if not symbol:
                    rows_skipped += 1
                    continue
                raw_qty = _attr(element, "quantity", "shares")
                raw_price = _attr(element, "tradePrice", "price")
                raw_date = _attr(element, "tradeDate", "dateTime", "date")
                if (
                    (raw_qty is not None and not _is_number(raw_qty))
                    or (raw_price is not None and not _is_number(raw_price))
                    # A missing or invalid date is never replaced with today:
                    # the row is skipped (a fabricated trade_date would poison
                    # the FIFO tax ledger).
                    or raw_date is None
                    or not _is_date(raw_date)
                ):
                    rows_skipped += 1
                    continue
                external_id = _attr(element, "tradeID", "transactionID", "ibExecID")
                if external_id and external_id in existing_ids:
                    trades_already_present += 1
                    continue
                if _is_cancel_trade(element):
                    cancel_company = self._company_by_symbol(db, symbol)
                    original = (
                        _find_cancelled_trade(db, element, cancel_company, file_trades)
                        if cancel_company is not None
                        else None
                    )
                    if original is None:
                        rows_skipped += 1
                        row_errors.append(
                            f"Anulacion {external_id or '?'} de {symbol}: no se localizo una unica operacion "
                            "original, se omite; revisa esa operacion a mano."
                        )
                        continue
                    # La original deja de ser compra/venta (no cuenta en posicion, FIFO ni
                    # diario) y se conserva con su rastro; la anulacion queda como fila propia.
                    original.action = "cancelled"
                    original.raw_payload = {**(original.raw_payload or {}), "cancelled_by": external_id}
                    db.add(
                        Transaction(
                            portfolio_id=portfolio.id,
                            company_id=cancel_company.id,
                            trade_date=_date(_attr(element, "tradeDate", "dateTime", "date")),
                            action="cancel",
                            quantity=abs(_decimal(_attr(element, "quantity", "shares"))),
                            price=_decimal(_attr(element, "tradePrice", "price")),
                            fees=abs(_decimal(_attr(element, "ibCommission", "commission", "fees"))),
                            currency=_attr(element, "currency") or cancel_company.currency,
                            external_id=external_id,
                            raw_payload={**dict(element.attrib), "cancels": original.external_id},
                        )
                    )
                    if external_id:
                        existing_ids.add(external_id)
                    trades_cancelled += 1
                    continue
                if (
                    trades_only
                    and only_existing_companies
                    and symbol.upper().strip() not in companies
                    and db.scalar(select(Company.id).where(Company.ticker == symbol.upper().strip())) is None
                ):
                    unknown_tickers[symbol.upper().strip()] = unknown_tickers.get(symbol.upper().strip(), 0) + 1
                    continue
                company = self._company(db, companies, symbol)
                self._capture_isin(company, element)
                action = self._action(_attr(element, "buySell", "transactionType", "tradeType"))
                quantity = abs(_decimal(_attr(element, "quantity", "shares")))
                transaction = Transaction(
                    portfolio_id=portfolio.id,
                    company_id=company.id,
                    trade_date=_date(_attr(element, "tradeDate", "dateTime", "date")),
                    action=action,
                    quantity=quantity,
                    price=_decimal(_attr(element, "tradePrice", "price")),
                    fees=abs(_decimal(_attr(element, "ibCommission", "commission", "fees"))),
                    currency=_attr(element, "currency") or company.currency,
                    external_id=external_id,
                    raw_payload=dict(element.attrib),
                )
                if external_id:
                    # F364: se registra SOLO tras validar y crear la fila; un id
                    # repetido dentro del XML se importa una vez, y una fila
                    # inválida no oculta a una válida posterior con el mismo id.
                    existing_ids.add(external_id)
                db.add(transaction)
                file_trades.append(transaction)
                trades_imported += 1

            elif tag == "CashTransaction":
                raw_amount = _attr(element, "amount", "netCash", "proceeds")
                raw_date = _attr(element, "dateTime", "date", "tradeDate")
                if (
                    (raw_amount is not None and not _is_number(raw_amount))
                    or raw_date is None
                    or not _is_date(raw_date)
                ):
                    rows_skipped += 1
                    continue
                type_attr = (_attr(element, "type", "transactionType", "activityType") or "").lower()
                if "withholding" in type_attr or "tax" in type_attr:
                    # Withheld tax arrives as its own CashTransaction with the
                    # gross dividend. Mapping it to cash_misc erased the
                    # discriminator, so the tax report declared the gross and
                    # never credited the retention.
                    action = "withholding"
                elif "dividend" in type_attr or any(
                    token in type_attr
                    for token in (
                        "lieu",
                        "return of capital",
                        "capital return",
                        "lending",
                        "substitute payment",
                    )
                ):
                    # Pagos especiales (payment in lieu, return of capital,
                    # stock lending): llegan al informe como "dividend" para
                    # NO perderse, y allí el detector de tipos originales los
                    # excluye de las sumas ordinarias (revisión manual).
                    action = "dividend"
                elif "interest" in type_attr:
                    action = "interest"
                elif "fee" in type_attr or "commission" in type_attr:
                    action = "fee"
                else:
                    action = "cash_misc"
                if trades_only and action == "cash_misc":
                    cash_misc_skipped += 1
                    continue
                external_id = _attr(element, "trxID", "transactionID", "id")
                if external_id and external_id in existing_ids:
                    continue
                amount = _decimal(_attr(element, "amount", "netCash", "proceeds"))
                # CashTransaction carries the symbol in most Flex exports. The
                # row used to be written with company_id=None, and the tax
                # report INNER JOINs Company, so every imported dividend and
                # every retention vanished from the filing.
                cash_symbol = _attr(
                    element, "symbol", "underlyingSymbol", "description"
                )
                cash_company = self._company_by_symbol(db, cash_symbol)
                if cash_company is None and cash_symbol:
                    unattributed += 1
                transaction = Transaction(
                    portfolio_id=portfolio.id,
                    company_id=cash_company.id if cash_company is not None else None,
                    trade_date=_date(_attr(element, "dateTime", "date", "tradeDate")),
                    action=action,
                    quantity=Decimal("1"),
                    price=amount,
                    fees=Decimal("0"),
                    currency=_attr(element, "currency") or "USD",
                    external_id=external_id,
                    raw_payload=dict(element.attrib),
                )
                if external_id:
                    # F364: se registra SOLO tras validar y crear la fila; un id
                    # repetido dentro del XML se importa una vez, y una fila
                    # inválida no oculta a una válida posterior con el mismo id.
                    existing_ids.add(external_id)
                db.add(transaction)
                if action == "dividend":
                    dividends_imported += 1
                elif action == "fee":
                    fees_imported += 1
                else:
                    cash_transactions_imported += 1

            elif tag == "CorporateAction":
                ca_type = (_attr(element, "type", "activityType") or "").upper()
                if ca_type not in {"DIV", "DIVIDEND", "PD", "PI"}:
                    continue
                action = "dividend"
                external_id = _attr(element, "transactionID", "id")
                if external_id and external_id in existing_ids:
                    continue
                raw_date = _attr(element, "dateTime", "date", "tradeDate")
                if raw_date is None or not _is_date(raw_date):
                    rows_skipped += 1
                    continue
                symbol = _attr(element, "symbol", "underlyingSymbol")
                company_id = None
                if symbol:
                    corp_company = self._company(db, companies, symbol)
                    company_id = corp_company.id
                amount = _decimal(_attr(element, "amount", "proceeds", "netCash"))
                transaction = Transaction(
                    portfolio_id=portfolio.id,
                    company_id=company_id,
                    trade_date=_date(_attr(element, "dateTime", "date", "tradeDate")),
                    action=action,
                    quantity=Decimal("1"),
                    price=amount,
                    fees=Decimal("0"),
                    currency=_attr(element, "currency") or "USD",
                    external_id=external_id,
                    raw_payload=dict(element.attrib),
                )
                if external_id:
                    # F364: se registra SOLO tras validar y crear la fila; un id
                    # repetido dentro del XML se importa una vez, y una fila
                    # inválida no oculta a una válida posterior con el mismo id.
                    existing_ids.add(external_id)
                db.add(transaction)
                dividends_imported += 1

        if trades_only:
            db.flush()
            result = {
                "status": "dry_run" if dry_run else "imported",
                "trades_imported": trades_imported,
                "trades_already_present": trades_already_present,
                "trades_cancelled": trades_cancelled,
                "non_stock_skipped": non_stock_skipped,
                "dividends_imported": dividends_imported,
                "fees_imported": fees_imported,
                "cash_transactions_imported": cash_transactions_imported,
                "cash_misc_skipped": cash_misc_skipped,
                "skipped_unknown_tickers": dict(sorted(unknown_tickers.items())),
                "rows_skipped": rows_skipped,
                "row_errors": row_errors,
            }
            if dry_run:
                db.rollback()
            else:
                db.commit()
                _auto_link_journal_after_import(db)
            return result

        positions_closed: list[str] = []
        cash_removed: list[str] = []
        reconcile_blocked: list[str] = []
        if reconcile:
            db.flush()
            reconcile_blocked = _snapshot_blockers(
                root,
                expected_account_id=expected_account_id or "",
                positions_imported=positions_imported,
                position_rows_skipped=position_rows_skipped,
                cash_rows_skipped=cash_rows_skipped,
                cash_imported=cash_imported,
                max_age_days=max_statement_age_days,
                query_complete_attested=query_complete_attested,
            )
            if not reconcile_blocked:
                allowed = set(reconcile_sources)
                for stale in db.scalars(select(Position)).all():
                    if stale.company_id not in imported_company_ids and stale.source in allowed:
                        company = db.get(Company, stale.company_id)
                        positions_closed.append(company.ticker if company else str(stale.company_id))
                        if not dry_run:
                            db.delete(stale)
                for stale_cash in db.scalars(select(CashBalance)).all():
                    if stale_cash.currency not in imported_cash_currencies and stale_cash.source in allowed:
                        cash_removed.append(stale_cash.currency)
                        if not dry_run:
                            db.delete(stale_cash)
            db.flush()
            if dry_run:
                db.rollback()
                return {
                    "status": "dry_run",
                    "would_close_positions": sorted(positions_closed),
                    "would_remove_cash": sorted(cash_removed),
                    "reconcile_blocked": reconcile_blocked,
                    "positions_in_statement": positions_imported,
                    "cash_in_statement": cash_imported,
                }

        from app.services.portfolio_snapshot_service import PortfolioSnapshotService

        # SessionLocal usa autoflush=False: sin flush las filas importadas no se ven.
        db.flush()
        observation_dates = [
            position.as_of for position in db.scalars(select(Position)).all()
        ] + [cash.as_of for cash in db.scalars(select(CashBalance)).all()]
        snapshot = PortfolioSnapshotService().capture(
            db,
            as_of=max(observation_dates, default=date.today()),
            source="ibkr_flex",
        )
        from app.services.ibkr_cost_reconciliation import reconcile_ibkr_costs

        checked_positions = list(db.scalars(select(Position)).all())
        cost_checks = reconcile_ibkr_costs(db, checked_positions)
        cost_review_required = sorted(
            p.company.ticker for p in checked_positions
            if cost_checks.get(p.id, {}).get("status") == "review_required"
        )
        db.commit()
        _auto_link_journal_after_import(db)
        # market_prices solo acumula hacia adelante: las companias que la
        # importacion estrena en cartera no tienen pasado. Backfill de ~1 ano
        # en segundo plano, una compania por tarea; la cola nunca rompe una
        # importacion ya confirmada.
        price_backfills_enqueued = 0
        try:
            from app.services.market_close_sync import enqueue_price_backfills

            # Escalonado interno: N companias nuevas no disparan N llamadas
            # simultaneas contra Yahoo (delay incremental por tarea).
            price_backfills_enqueued = enqueue_price_backfills(
                db,
                imported_company_ids,
                tenant_id=(
                    db.info["tenant_id"]
                    if type(db.info.get("tenant_id")) is int
                    else None
                ),
                user_id=str(db.info["user_id"]) if db.info.get("user_id") else None,
            )
        except Exception:  # noqa: BLE001 - cola caida: la importacion ya es valida
            db.rollback()
        return {
            "status": "imported",
            "price_backfills_enqueued": price_backfills_enqueued,
            "positions_imported": positions_imported,
            "valuation_hold_kept": valuation_hold_kept,
            "cost_review_required": cost_review_required,
            "cash_imported": cash_imported,
            "trades_imported": trades_imported,
            "trades_cancelled": trades_cancelled,
            "dividends_imported": dividends_imported,
            "fees_imported": fees_imported,
            "cash_transactions_imported": cash_transactions_imported,
            "rows_skipped": rows_skipped,
            "unattributed_cash_rows": unattributed,
            "row_errors": row_errors,
            "positions_closed": sorted(positions_closed),
            "cash_removed": sorted(cash_removed),
            "reconcile_blocked": reconcile_blocked,
            "portfolio_snapshot_id": snapshot.id,
        }

    @staticmethod
    def _company_by_symbol(db: Session, symbol: str | None) -> Company | None:
        """Resolve a Flex symbol to a Company, tolerating broker suffixes.

        Flex reports ``AAPL``, ``AAPL.US``, ``SAN.MC`` or a free-text
        ``description``; only the bare local ticker is a Company.ticker.
        """
        if not symbol:
            return None
        text = str(symbol).strip()
        if not text:
            return None
        candidates = [text]
        for separator in (".", " ", "/"):
            if separator in text:
                candidates.append(text.split(separator, 1)[0])
        upper = {candidate.upper() for candidate in candidates if candidate}
        if not upper:
            return None
        return db.scalar(
            select(Company).where(Company.ticker.in_(sorted(upper))).limit(1)
        )

    def import_ibkr_csv(self, db: Session, csv_text: str) -> dict:
        """Importa operaciones desde un CSV de actividad de IBKR.

        Formato: cabecera con symbol, action, quantity, price y date (más
        fees y currency opcionales) + una fila por operación. Las filas
        inválidas se omiten y se describen en ``row_errors`` en español;
        los errores fatales (cabecera ausente, fichero vacío) lanzan
        :class:`IBKRImportError`.
        """
        from app.services.portfolio_ledger_service import PortfolioLedgerService

        errors = validate_ibkr_csv(csv_text)
        fatal_errors = [error for error in errors if not error.startswith("Fila ")]
        if fatal_errors:
            raise IBKRImportError(" ".join(fatal_errors))
        row_errors = [error for error in errors if error.startswith("Fila ")]
        bad_lines = {int(error.split(" ")[1]) for error in row_errors if error.split(" ")[1].isdigit()}

        data_rows = [row for row in _csv_rows(csv_text) if any(cell.strip() for cell in row)]
        mapping = _map_csv_columns(data_rows[0])
        assert mapping is not None  # garantizado por validate_ibkr_csv
        ledger = PortfolioLedgerService()
        trades_imported = 0
        duplicate_trades = 0
        occurrences: Counter[str] = Counter()
        legacy_occurrences: Counter[str] = Counter()
        legacy_reimport_blocked = 0
        has_rows_without_id = False
        rows_skipped = len(bad_lines)
        # Se reproduce de la fecha mas antigua a la mas nueva: un export con lo
        # mas reciente primero evaluaria la venta antes de su compra y el libro
        # la rechazaria. sorted() es estable; con la misma fecha las compras van
        # antes que las ventas (el CSV no trae hora, y una venta sin compra
        # previa el libro la rechaza igualmente). `line_number` sigue siendo la
        # linea ORIGINAL del fichero para row_errors.
        def _row_sort_key(item: tuple[int, list[str]]) -> tuple[str, int, int]:
            line_no, raw = item
            date_pos = mapping.get("date")
            action_pos = mapping.get("action")
            try:
                day = _date(raw[date_pos].strip()).isoformat() if date_pos is not None else "9999-12-31"
            except Exception:  # noqa: BLE001 - las filas invalidas ya estan en bad_lines
                day = "9999-12-31"
            kind = (
                _csv_trade_action(raw[action_pos])
                if action_pos is not None and action_pos < len(raw)
                else None
            )
            return (day, 0 if kind == "buy" else 1, line_no)

        for line_number, row in sorted(enumerate(data_rows[1:], start=2), key=_row_sort_key):
            if line_number in bad_lines:
                continue
            def _cell(name: str) -> str:
                position = mapping.get(name)
                if position is None or position >= len(row):
                    return ""
                return row[position].strip()

            symbol = _cell("symbol").upper()
            action = _csv_trade_action(_cell("action"))
            if action is None:
                # La validación anterior ya marca y omite estas filas.
                continue
            # Provider IDs share identity with Flex XML. Without one, use the
            # canonical economic row plus occurrence count, preserving two
            # identical fills in one file while making replay/reordering safe.
            values = [symbol, action, str(abs(_csv_decimal(_cell("quantity")).normalize())),
                      str(_csv_decimal(_cell("price")).normalize()),
                      _date(_cell("date")).isoformat(),
                      str(abs(_csv_decimal(_cell("fees")).normalize())) if _cell("fees") else "0",
                      _cell("currency").upper() or "USD"]
            fingerprint = hashlib.sha256(json.dumps(values).encode()).hexdigest()
            occurrences[fingerprint] += 1
            has_rows_without_id |= not bool(_cell("external_id"))
            external_id = _cell("external_id") or f"ibkr-csv-{fingerprint}-{occurrences[fingerprint]}"
            if len(external_id) > 120:
                rows_skipped += 1
                row_errors.append(f"Fila {line_number} del CSV: identificador de operación demasiado largo.")
                continue
            if db.scalar(
                select(Transaction.id).where(
                    Transaction.external_id == external_id,
                    *tenant_filters(db, Transaction),
                )
            ) is not None:
                duplicate_trades += 1
                continue
            if not _cell("external_id"):
                # Before _csv_decimal, cells with a decimal comma were stored
                # with corrupted values (12,50 -> 1250) under THAT fingerprint.
                # Re-importing the same file would insert a corrected twin of a
                # row already in the ledger. If the legacy identity exists, the
                # row is blocked with an explanation and nothing is mutated.
                legacy_values = _legacy_csv_values(symbol, action, _cell)
                if legacy_values is not None and legacy_values != values:
                    legacy_fp = hashlib.sha256(json.dumps(legacy_values).encode()).hexdigest()
                    legacy_occurrences[legacy_fp] += 1
                    legacy_id = f"ibkr-csv-{legacy_fp}-{legacy_occurrences[legacy_fp]}"
                    if db.scalar(
                        select(Transaction.id).where(
                            Transaction.external_id == legacy_id,
                            *tenant_filters(db, Transaction),
                        )
                    ) is not None:
                        rows_skipped += 1
                        legacy_reimport_blocked += 1
                        row_errors.append(
                            f"Fila {line_number} del CSV: ya existe una operacion importada antes con "
                            "esta misma fila leida con decimales corruptos (coma decimal). No se "
                            "duplica ni se modifica; revisa y corrige la operacion existente a mano."
                        )
                        continue
            try:
                with db.begin_nested():
                    transaction = ledger.create_transaction(
                        db,
                        ticker=symbol,
                        action=action,
                        quantity=abs(_csv_decimal(_cell("quantity"))),
                        price=_csv_decimal(_cell("price")),
                        trade_date=_date(_cell("date")),
                        fees=abs(_csv_decimal(_cell("fees"))) if _cell("fees") else Decimal("0"),
                        currency=_cell("currency").upper() or "USD",
                    )
                    transaction.external_id = external_id
                    transaction.raw_payload = {**transaction.raw_payload, "source": "ibkr_csv", "identity": "provider" if _cell("external_id") else "canonical_occurrence"}
                    db.flush()
                    trades_imported += 1
            except IntegrityError:
                # A concurrent identical upload won the unique (tenant, external_id)
                # race. The savepoint also restores its position rebuild.
                if db.scalar(
                    select(Transaction.id).where(
                        Transaction.external_id == external_id,
                        *tenant_filters(db, Transaction),
                    )
                ) is None:
                    raise
                duplicate_trades += 1
            except ValueError as exc:
                rows_skipped += 1
                row_errors.append(
                    f"Fila {line_number} del CSV ({symbol}): no se pudo registrar "
                    f"({exc}). Revisa los valores de la fila."
                )
        identity_warning = None
        if has_rows_without_id:
            identity_warning = (
                "CSV sin identificador de operación: se comparan símbolo, acción, cantidad, "
                "precio, fecha, comisión y divisa, conservando las repeticiones del archivo. "
                "Dos archivos parciales con operaciones idénticas no se pueden distinguir; "
                "usa tradeID para importarlos sin ambigüedad."
            )
        db.commit()
        _auto_link_journal_after_import(db)
        return {
            "status": "imported",
            "trades_imported": trades_imported,
            "duplicate_trades": duplicate_trades,
            "legacy_reimport_blocked": legacy_reimport_blocked,
            "identity_warning": identity_warning,
            "rows_skipped": rows_skipped,
            "row_errors": row_errors,
        }

    def _company(self, db: Session, cache: dict[str, Company], symbol: str) -> Company:
        ticker = symbol.upper().strip()
        if ticker in cache:
            return cache[ticker]
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            company = Company(
                ticker=ticker,
                name=ticker,
                exchange="UNKNOWN",
                currency="USD",
                sector="Unknown",
                industry="Unknown",
                company_type="imported_holding",
                valuation_model="unassigned",
                special_sources=["IBKR"],
                special_risks=[],
                factor_tags=[],
            )
            db.add(company)
            db.flush()
        cache[ticker] = company
        # Enriquecer el placeholder con el nombre real desde las APIs de datos.
        # nosemgrep: gerarai-broad-except-pass -- enriquecimiento opcional; nunca bloquea el import
        try:
            from app.services.company_enrichment_service import CompanyEnrichmentService

            CompanyEnrichmentService().enrich(db, company)
        except Exception:  # noqa: BLE001 — nunca bloquear el import por el enriquecimiento
            pass
        return company

    @staticmethod
    def _capture_isin(company: Company, element: ElementTree.Element) -> None:
        """Rellena ``Company.isin`` desde el Flex XML (atributo ``isin``).

        Solo se escribe cuando el valor está vacío: un ISIN nunca se pisa con
        otro distinto (un conflicto indicaría símbolo reutilizado y se deja
        para revisión manual en vez de mezclar valores).
        """
        isin = (_attr(element, "isin") or "").strip().upper()
        if isin and len(isin) == 12 and not company.isin:
            company.isin = isin

    def _action(self, value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"buy", "bot", "b"}:
            return "buy"
        if normalized in {"sell", "sold", "s"}:
            return "sell"
        return normalized or "trade"
