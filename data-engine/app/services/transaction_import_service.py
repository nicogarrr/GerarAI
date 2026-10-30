"""Servicio de importación masiva de transacciones desde CSV o Excel.

Fulfills: VAL-DATA-006 (y satisface VAL-DATA-007)
Expected Behavior:
- Subida de archivos CSV o Excel (XLSX)
- Mapeo flexible de columnas para ticker, date, quantity, price, action
- Soporte de múltiples formatos de fecha (YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, etc.)
- Validación estricta previa con informe detallado de errores por fila
- Modo vista previa (preview) para revisar antes de confirmar
- Inserción atómica y registro en el log de auditoría
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.services.audit_service import record_audit_event
from app.services.number_parsing import parse_localized_number
from app.services.portfolio_ledger_service import PortfolioLedgerService, PortfolioOversellError


class RowValidationError(BaseModel):
    row_number: int
    field: str
    message: str
    raw_value: str | None = None


class ParsedTransaction(BaseModel):
    row_number: int
    ticker: str
    date: str
    action: str
    quantity: float
    price: float
    fees: float = 0.0
    currency: str = "EUR"
    notes: str | None = None


class TransactionImportPreviewResponse(BaseModel):
    success: bool
    total_rows: int
    valid_rows_count: int
    invalid_rows_count: int
    detected_columns: dict[str, str]
    preview_items: list[ParsedTransaction]
    errors: list[RowValidationError]


class TransactionImportCommitRequest(BaseModel):
    transactions: list[ParsedTransaction] = Field(min_length=1, max_length=2000)


def _normalize_header(header: str) -> str:
    """Normaliza nombres de columna (minúsculas, sin acentos ni espacios)."""
    norm = unicodedata.normalize("NFKD", str(header)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", norm.lower())


_COLUMN_CANDIDATES: list[tuple[str, tuple[str, ...]]] = [
    ("date", ("date", "fecha", "tradedate", "fechaoperacion", "dia", "fechacompra")),
    ("ticker", ("ticker", "simbolo", "symbol", "activo", "instrumento", "isin", "nemotecnico")),
    ("action", ("tipo", "action", "operacion", "type", "side", "direction", "sentido")),
    ("quantity", ("quantity", "cantidad", "shares", "titulos", "volumen", "unidades", "numero")),
    ("price", ("price", "precio", "cotizacion", "coste", "valorunitario", "preciounitario")),
    ("fees", ("fees", "fee", "comision", "comisiones", "gastos", "corretaje")),
    ("currency", ("currency", "moneda", "divisa", "ccy")),
]


def auto_detect_columns(headers: list[str]) -> dict[str, str]:
    """Detecta automáticamente el mapeo de columnas según cabeceras con dos pasadas (exacta y parcial)."""
    mapping: dict[str, str] = {}
    normalized = [_normalize_header(h) for h in headers]
    used_indices: set[int] = set()

    # Pasada 1: coincidencia exacta normalizada
    for target_col, candidates in _COLUMN_CANDIDATES:
        for idx, norm_h in enumerate(normalized):
            if idx in used_indices:
                continue
            if norm_h in candidates:
                mapping[target_col] = headers[idx]
                used_indices.add(idx)
                break

    # Pasada 2: coincidencia de subcadena en cabeceras no asignadas
    for target_col, candidates in _COLUMN_CANDIDATES:
        if target_col in mapping:
            continue
        for idx, norm_h in enumerate(normalized):
            if idx in used_indices:
                continue
            if any(cand in norm_h for cand in candidates):
                mapping[target_col] = headers[idx]
                used_indices.add(idx)
                break

    return mapping


def _parse_decimal(raw: Any) -> Decimal | None:
    """Parsea un número localizado devolviendo Decimal con su signo."""
    res = parse_localized_number(raw)
    if res is None:
        return None
    val, _ = res
    return val


def parse_flexible_date(raw_date: Any) -> date:
    """Parsea una fecha aceptando formatos estándar españoles e internacionales."""
    if isinstance(raw_date, datetime):
        return raw_date.date()
    if isinstance(raw_date, date):
        return raw_date

    date_str = str(raw_date).strip()
    if not date_str:
        raise ValueError("La fecha no puede estar vacía")

    # Si viene con hora ISO
    date_str = date_str.split("T")[0].split(" ")[0].strip()

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%Y%m%d",
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt).date()
            if parsed > local_today():
                raise ValueError(f"La fecha de operación no puede ser futura ({parsed.isoformat()})")
            return parsed
        except ValueError as exc:
            if "futura" in str(exc):
                raise
            continue

    raise ValueError(f"Formato de fecha irreconocible: '{date_str}'")


def normalize_action(raw_action: Any) -> str:
    """Normaliza el tipo de acción a buy/sell/dividend/deposit/withdrawal."""
    act = _normalize_header(str(raw_action))
    if act in ("buy", "compra", "c", "b", "comprar", "adquisicion"):
        return "buy"
    if act in ("sell", "venta", "v", "s", "vender"):
        return "sell"
    if act in ("dividend", "dividendo", "div", "cobrodividendo"):
        return "dividend"
    if act in ("deposit", "deposito", "ingreso", "abono"):
        return "deposit"
    if act in ("withdrawal", "retirada", "cargo", "reintegro"):
        return "withdrawal"
    raise ValueError(f"Tipo de operación no reconocido: '{raw_action}' (se esperaba compra, venta o dividendo)")


def parse_file_rows(file_bytes: bytes, filename: str = "") -> tuple[list[str], list[list[str]]]:
    """Extrae cabeceras y filas de texto desde CSV o archivo Excel XLSX."""
    filename_lower = filename.lower()

    if filename_lower.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet = wb.active
            rows: list[list[str]] = []
            for r in sheet.iter_rows(values_only=True):
                if any(v is not None for v in r):
                    rows.append([str(v) if v is not None else "" for v in r])
            if not rows:
                raise ValueError("El archivo Excel no contiene filas con datos")
            headers = rows[0]
            data_rows = rows[1:]
            return headers, data_rows
        except Exception as exc:
            raise ValueError(f"Error al leer el archivo Excel: {exc}") from exc

    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except Exception as exc:
            raise ValueError("No se pudo decodificar el archivo como texto (se esperaba UTF-8 o Latin-1)") from exc

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("El archivo CSV está vacío")

    first_line = lines[0]
    delimiter = ","
    if first_line.count(";") > first_line.count(","):
        delimiter = ";"
    elif first_line.count("\t") > first_line.count(","):
        delimiter = "\t"

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_rows = list(reader)
    if not all_rows:
        raise ValueError("El archivo CSV no contiene registros válidos")

    headers = [h.strip() for h in all_rows[0]]
    data_rows = [[cell.strip() for cell in row] for row in all_rows[1:] if any(c.strip() for c in row)]
    return headers, data_rows


class TransactionImportService:
    """Gestiona la validación y confirmación de transacciones importadas."""

    def preview_import(
        self,
        file_bytes: bytes,
        filename: str = "",
        custom_mapping: dict[str, str] | None = None,
    ) -> TransactionImportPreviewResponse:
        """Parsea el archivo, valida cada registro y genera el informe previo de errores."""
        headers, data_rows = parse_file_rows(file_bytes, filename)

        detected_mapping = auto_detect_columns(headers)
        if custom_mapping:
            detected_mapping.update(custom_mapping)

        required_fields = ["ticker", "date", "quantity", "price"]
        errors: list[RowValidationError] = []

        missing_fields = [f for f in required_fields if f not in detected_mapping]
        if missing_fields:
            for mf in missing_fields:
                errors.append(
                    RowValidationError(
                        row_number=0,
                        field=mf,
                        message=f"No se encontró la columna obligatoria '{mf}' en la cabecera",
                    )
                )
            return TransactionImportPreviewResponse(
                success=False,
                total_rows=len(data_rows),
                valid_rows_count=0,
                invalid_rows_count=len(data_rows),
                detected_columns=detected_mapping,
                preview_items=[],
                errors=errors,
            )

        header_indices = {h: i for i, h in enumerate(headers)}
        col_indices = {k: header_indices.get(v, -1) for k, v in detected_mapping.items()}

        preview_items: list[ParsedTransaction] = []
        action_default = "buy"

        for row_idx, row in enumerate(data_rows, start=2):
            row_has_error = False

            def get_val(key: str) -> str:
                idx = col_indices.get(key, -1)
                if 0 <= idx < len(row):
                    return row[idx].strip()
                return ""

            # Ticker
            ticker_raw = get_val("ticker").upper()
            if not ticker_raw:
                errors.append(RowValidationError(row_number=row_idx, field="ticker", message="El ticker es obligatorio"))
                row_has_error = True
            elif not re.match(r"^[A-Z0-9_\.-]{1,20}$", ticker_raw):
                errors.append(RowValidationError(row_number=row_idx, field="ticker", message="Formato de ticker no válido", raw_value=ticker_raw))
                row_has_error = True

            # Fecha
            date_raw = get_val("date")
            parsed_date_str = ""
            try:
                dt = parse_flexible_date(date_raw)
                parsed_date_str = dt.isoformat()
            except ValueError as exc:
                errors.append(RowValidationError(row_number=row_idx, field="date", message=str(exc), raw_value=date_raw))
                row_has_error = True

            # Acción
            action_raw = get_val("action")
            parsed_action = action_default
            if action_raw:
                try:
                    parsed_action = normalize_action(action_raw)
                except ValueError as exc:
                    errors.append(RowValidationError(row_number=row_idx, field="action", message=str(exc), raw_value=action_raw))
                    row_has_error = True

            # Cantidad
            qty_raw = get_val("quantity")
            qty_num = 0.0
            parsed_qty = _parse_decimal(qty_raw)
            if parsed_qty is None:
                errors.append(RowValidationError(row_number=row_idx, field="quantity", message="Cantidad no numérica o ausente", raw_value=qty_raw))
                row_has_error = True
            elif parsed_qty <= 0 and parsed_action in ("buy", "sell"):
                errors.append(RowValidationError(row_number=row_idx, field="quantity", message="La cantidad debe ser mayor que cero", raw_value=qty_raw))
                row_has_error = True
            else:
                qty_num = float(parsed_qty)

            # Precio
            price_raw = get_val("price")
            price_num = 0.0
            parsed_price = _parse_decimal(price_raw)
            if parsed_price is None:
                errors.append(RowValidationError(row_number=row_idx, field="price", message="Precio no numérico o ausente", raw_value=price_raw))
                row_has_error = True
            elif parsed_price < 0:
                errors.append(RowValidationError(row_number=row_idx, field="price", message="El precio no puede ser negativo", raw_value=price_raw))
                row_has_error = True
            else:
                price_num = float(parsed_price)

            # Comisiones
            fees_raw = get_val("fees")
            fees_num = 0.0
            if fees_raw:
                pf = _parse_decimal(fees_raw)
                if pf is not None and pf >= 0:
                    fees_num = float(pf)

            # Divisa
            currency_raw = get_val("currency").upper() or "EUR"

            if not row_has_error:
                preview_items.append(
                    ParsedTransaction(
                        row_number=row_idx,
                        ticker=ticker_raw,
                        date=parsed_date_str,
                        action=parsed_action,
                        quantity=qty_num,
                        price=price_num,
                        fees=fees_num,
                        currency=currency_raw,
                    )
                )

        invalid_count = len({e.row_number for e in errors if e.row_number > 0})
        return TransactionImportPreviewResponse(
            success=len(errors) == 0,
            total_rows=len(data_rows),
            valid_rows_count=len(preview_items),
            invalid_rows_count=invalid_count,
            detected_columns=detected_mapping,
            preview_items=preview_items,
            errors=errors,
        )

    def commit_import(
        self,
        db: Session,
        transactions: list[ParsedTransaction],
    ) -> dict[str, Any]:
        """Inserta atómicamente todas las transacciones validadas en la cartera."""
        if not transactions:
            raise ValueError("No hay transacciones para importar")

        service = PortfolioLedgerService()
        inserted_count = 0

        try:
            for tx in transactions:
                service.create_transaction(
                    db,
                    ticker=tx.ticker,
                    action=tx.action,
                    quantity=Decimal(str(tx.quantity)),
                    price=Decimal(str(tx.price)),
                    trade_date=date.fromisoformat(tx.date),
                    fees=Decimal(str(tx.fees)),
                    currency=tx.currency,
                    notes=tx.notes or f"Importación masiva (fila {tx.row_number})",
                )
                inserted_count += 1

            record_audit_event(
                db=db,
                action="IMPORT_BATCH",
                resource_type="transactions",
                after_state={"count": inserted_count, "tickers": list({t.ticker for t in transactions})},
            )
            db.commit()
            return {
                "success": True,
                "message": f"Se han importado exitosamente {inserted_count} transacciones",
                "imported_count": inserted_count,
            }
        except PortfolioOversellError as exc:
            db.rollback()
            raise ValueError(f"Error de sobreventa en cartera durante la importación: {exc}") from exc
        except Exception:
            db.rollback()
            raise
