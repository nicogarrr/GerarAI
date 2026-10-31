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
import hashlib
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.core.tenancy import tenant_filters
from app.models.entities import Company, Transaction
from app.services.audit_service import record_audit_event
from app.services.document_ingestion_service import guard_ooxml_zip
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
    warnings: list[RowValidationError] = []


class TransactionImportCommitRequest(BaseModel):
    transactions: list[ParsedTransaction] = Field(min_length=1, max_length=2000)
    source_filename: str | None = None


# Limites duros de ingesta para archivos subidos por el usuario: el parseo es
# en memoria, asi que un archivo sin tope es un vector de denegacion de
# servicio (memoria/CPU). 10 MB sobra para un extracto de broker real (el
# commit admite lotes de 2000 operaciones); 20.000 filas es ~10x ese lote.
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 20_000


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


_DMY_LIKE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{4}$")


def detect_month_first(raw_dates: list[str]) -> bool:
    """True si el fichero escribe las fechas como MM/DD/AAAA (formato americano).

    Basta una fila que solo cabe como mes/día (12/31/2024) para saber el orden
    del fichero entero; si también hay alguna que solo cabe como día/mes, el
    fichero es incoherente y se mantiene el orden español por defecto.
    """
    month_first = day_first = False
    for raw in raw_dates:
        match = _DMY_LIKE.match(str(raw).strip().split("T")[0].split(" ")[0])
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12 >= second:
            day_first = True
        elif second > 12 >= first:
            month_first = True
    return month_first and not day_first


def parse_flexible_date(raw_date: Any, *, month_first: bool = False) -> date:
    """Parsea una fecha aceptando formatos estándar españoles e internacionales.

    ``month_first``: el fichero usa MM/DD/AAAA (ver ``detect_month_first``), así
    que una fecha ambigua como 03/04/2024 es el 4 de marzo, no el 3 de abril.
    """
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
    if month_first:
        formats = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%Y%m%d"]

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
        # Un XLSX es un ZIP: sin guarda, un archivo pequeno puede expandirse a
        # cientos de MB en memoria (zip bomb). Misma guarda que la ingesta de
        # documentos, aplicada antes de abrir con openpyxl.
        guard_ooxml_zip(file_bytes)
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet = wb.active
            rows: list[list[str]] = []
            for r in sheet.iter_rows(values_only=True):
                if any(v is not None for v in r):
                    rows.append([str(v) if v is not None else "" for v in r])
        except Exception as exc:
            raise ValueError(f"Error al leer el archivo Excel: {exc}") from exc
        # Fuera del try: el límite de filas y el archivo vacío llegan con su
        # propio mensaje, no envueltos en «Error al leer el archivo Excel».
        if not rows:
            raise ValueError("El archivo Excel no contiene filas con datos")
        headers = rows[0]
        data_rows = rows[1:]
        if len(data_rows) > MAX_IMPORT_ROWS:
            raise ValueError(
                f"El archivo supera el máximo de {MAX_IMPORT_ROWS} filas; divídelo en varios lotes"
            )
        return headers, data_rows

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
    if len(data_rows) > MAX_IMPORT_ROWS:
        raise ValueError(
            f"El archivo supera el máximo de {MAX_IMPORT_ROWS} filas; divídelo en varios lotes"
        )
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
        warnings: list[RowValidationError] = []
        # Si el archivo tiene columna de acción, una celda vacía no puede
        # asumirse "compra" (una venta importada como compra corrompe la cartera).
        # Sin columna de acción en absoluto sí se asume compra (fichero simple de compras).
        action_column_mapped = "action" in detected_mapping
        # Columna ISIN explícita: el ISIN no es un ticker; hay que resolverlo a
        # la empresa registrada o rechazar la fila (nunca crear un ticker falso).
        ticker_header = detected_mapping.get("ticker", "")
        ticker_is_isin = _normalize_header(ticker_header) == "isin"
        seen_row_keys: dict[tuple, int] = {}
        date_idx = col_indices.get("date", -1)
        month_first = detect_month_first(
            [row[date_idx] for row in data_rows if 0 <= date_idx < len(row)]
        )

        for row_idx, row in enumerate(data_rows, start=2):
            row_has_error = False

            def get_val(key: str) -> str:
                idx = col_indices.get(key, -1)
                if 0 <= idx < len(row):
                    return row[idx].strip()
                return ""

            # Ingresos y retiradas de efectivo no son operaciones de cartera: el
            # ledger no los admite y confirmar el lote fallaría entero. Se
            # avisan y se omiten (antes la vista previa los daba por buenos).
            try:
                cash_action = normalize_action(get_val("action")) if get_val("action") else ""
            except ValueError:
                cash_action = ""
            if cash_action in ("deposit", "withdrawal"):
                label = "ingreso" if cash_action == "deposit" else "retirada"
                warnings.append(
                    RowValidationError(
                        row_number=row_idx,
                        field="action",
                        message=f"Movimiento de efectivo ({label}): no es una operación de cartera y se omite",
                        raw_value=get_val("action"),
                    )
                )
                continue

            # Ticker
            ticker_raw = get_val("ticker").upper()
            if not ticker_raw:
                errors.append(RowValidationError(row_number=row_idx, field="ticker", message="El ticker es obligatorio"))
                row_has_error = True
            elif ticker_is_isin:
                if not re.match(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$", ticker_raw):
                    errors.append(RowValidationError(row_number=row_idx, field="ticker", message="Formato de ISIN no válido", raw_value=ticker_raw))
                    row_has_error = True
                else:
                    warnings.append(
                        RowValidationError(
                            row_number=row_idx,
                            field="ticker",
                            message="La columna es ISIN: se resolverá al ticker registrado al importar (si no existe, la fila fallará)",
                            raw_value=ticker_raw,
                        )
                    )
            elif not re.match(r"^[A-Z0-9_\.-]{1,20}$", ticker_raw):
                errors.append(RowValidationError(row_number=row_idx, field="ticker", message="Formato de ticker no válido", raw_value=ticker_raw))
                row_has_error = True

            # Fecha
            date_raw = get_val("date")
            parsed_date_str = ""
            try:
                dt = parse_flexible_date(date_raw, month_first=month_first)
                parsed_date_str = dt.isoformat()
                # Día <= 12 con formato DD/MM: ambiguo con MM/DD americano; se avisa.
                if not month_first and dt.day <= 12 and re.match(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{4}$", date_raw.strip()):
                    warnings.append(
                        RowValidationError(
                            row_number=row_idx,
                            field="date",
                            message=f"Fecha ambigua '{date_raw.strip()}': se interpreta como día/mes/año ({dt.isoformat()})",
                            raw_value=date_raw,
                        )
                    )
            except ValueError as exc:
                errors.append(RowValidationError(row_number=row_idx, field="date", message=str(exc), raw_value=date_raw))
                row_has_error = True

            # Acción
            action_raw = get_val("action")
            parsed_action = "buy"
            if action_raw:
                try:
                    parsed_action = normalize_action(action_raw)
                except ValueError as exc:
                    errors.append(RowValidationError(row_number=row_idx, field="action", message=str(exc), raw_value=action_raw))
                    row_has_error = True
            elif action_column_mapped:
                errors.append(RowValidationError(row_number=row_idx, field="action", message="La acción está vacía (se esperaba compra, venta o dividendo)"))
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
                if pf is None:
                    # Una comisión ilegible no puede pasar a 0 en silencio: el
                    # coste de adquisición quedaría por debajo del real.
                    errors.append(RowValidationError(row_number=row_idx, field="fees", message="Comisión no numérica", raw_value=fees_raw))
                    row_has_error = True
                else:
                    # Los brokers (p. ej. DEGIRO) exportan los costes en negativo
                    # ("-2,00"): una comisión siempre es un coste, nunca un abono.
                    fees_num = float(abs(pf))

            # Divisa
            currency_raw = get_val("currency").upper() or "EUR"

            if not row_has_error:
                row_key = (ticker_raw, parsed_date_str, parsed_action, qty_num, price_num, fees_num, currency_raw)
                if row_key in seen_row_keys:
                    warnings.append(
                        RowValidationError(
                            row_number=row_idx,
                            field="row",
                            message=f"Fila duplicada: idéntica a la fila {seen_row_keys[row_key]} del propio archivo",
                            raw_value=ticker_raw,
                        )
                    )
                else:
                    seen_row_keys[row_key] = row_idx
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
            warnings=warnings,
        )

    def commit_import(
        self,
        db: Session,
        transactions: list[ParsedTransaction],
        source_filename: str | None = None,
    ) -> dict[str, Any]:
        """Inserta atómicamente las transacciones validadas, omitiendo duplicados exactos.

        Duplicados: una pata idéntica ya registrada (misma empresa, fecha, acción,
        cantidad, precio, comisión y divisa) se omite y se cuenta en
        ``duplicates_skipped``: reimportar el mismo fichero nunca duplica la cartera.
        Procedencia: cada pata lleva lote de importación, nombre de fichero y fila.
        """
        if not transactions:
            raise ValueError("No hay transacciones para importar")

        service = PortfolioLedgerService()
        inserted_count = 0
        duplicates_skipped = 0
        # Lote estable: huella del CONTENIDO del fichero (no aleatoria). Reimportar
        # el mismo CSV produce el mismo lote, lo que permite distinguir "mismo
        # fichero otra vez" (omite) de "otro fichero con patas idénticas" (importa).
        canonical = "\n".join(
            f"{t.ticker.upper()}|{t.date}|{t.action.lower()}|{t.quantity}|{t.price}|{t.fees}|{t.currency.upper()}|{t.notes or ''}|{t.row_number}"
            for t in transactions
        )
        import_batch = f"csv-{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"

        def _core_fingerprint(company_id: int, tx: ParsedTransaction) -> tuple:
            """Huella económica de la pata (sin cartera): qué operación es.

            La huella sola NO prueba identidad: dos compras reales idénticas el
            mismo día comparten huella. La identidad importada es
            (lote, huella, nº de ocurrencia) — ver _leg_prefix / el bucle.
            """
            return (
                company_id,
                date.fromisoformat(tx.date),
                tx.action.lower(),
                Decimal(str(tx.quantity)),
                Decimal(str(tx.price)),
                Decimal(str(tx.fees)),
                tx.currency.upper(),
            )

        def _leg_prefix(fp: tuple) -> str:
            digest = hashlib.sha256(repr(fp).encode()).hexdigest()[:16]
            return f"{import_batch}-{digest}-"

        def _legs_in_portfolio(prefix: str, portfolio_id: int | None) -> int:
            return db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.portfolio_id == portfolio_id,
                    Transaction.external_id.like(f"{prefix}%"),
                    *tenant_filters(db, Transaction),
                )
            ) or 0

        def _legs_in_tenant(prefix: str) -> int:
            return db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.external_id.like(f"{prefix}%"),
                    *tenant_filters(db, Transaction),
                )
            ) or 0


        seen_in_file: dict[tuple, int] = {}

        # Orden cronológico: una venta anterior a una compra listada después no
        # debe fallar por sobreventa. Mismo día: compras antes que ventas.
        def _chronological(tx: ParsedTransaction) -> tuple:
            action_rank = 0 if tx.action.lower() in ("buy", "deposit") else 1 if tx.action.lower() in ("sell", "withdrawal") else 2
            return (date.fromisoformat(tx.date), action_rank, tx.row_number)

        try:
            target_portfolio = service.fx.ensure_portfolio(db)
            for tx in sorted(transactions, key=_chronological):
                if re.match(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$", tx.ticker.upper()):
                    # Un ISIN no es un ticker: se resuelve a la empresa registrada.
                    company = db.scalar(select(Company).where(Company.isin == tx.ticker.upper()).limit(1))
                    if company is None:
                        raise ValueError(
                            f"ISIN {tx.ticker} sin empresa registrada (fila {tx.row_number}): "
                            "importa primero por ticker o registra la empresa con su ISIN"
                        )
                else:
                    # Ticker: la empresa se crea si no existe, para que la pata tenga
                    # identidad estable desde la PRIMERA importación (si no, reimportar
                    # el mismo fichero duplicaría las patas de empresas nuevas).
                    company = service.ensure_company(db, tx.ticker)
                fp = _core_fingerprint(company.id, tx)
                seen_in_file[fp] = seen_in_file.get(fp, 0) + 1
                prefix = _leg_prefix(fp)
                # Omite la ocurrencia k solo si ESTA cartera ya tiene k patas del
                # mismo lote y huella: dos compras idénticas legítimas importan las
                # dos, reimportar el mismo fichero no duplica, y la misma pata en
                # otra cartera del tenant no bloquea la importación en esta.
                if _legs_in_portfolio(prefix, target_portfolio.id) >= seen_in_file[fp]:
                    duplicates_skipped += 1
                    continue
                # external_id UNIQUE por tenant: la ocurrencia se numera en el
                # tenant para no chocar con patas movidas a otra cartera.
                leg_id = f"{prefix}{_legs_in_tenant(prefix) + 1}"
                origin = f"Importación masiva ({source_filename}, fila {tx.row_number})" if source_filename else f"Importación masiva (fila {tx.row_number})"
                service.create_transaction(
                    db,
                    ticker=company.ticker if company else tx.ticker,
                    action=tx.action,
                    quantity=Decimal(str(tx.quantity)),
                    price=Decimal(str(tx.price)),
                    trade_date=date.fromisoformat(tx.date),
                    fees=Decimal(str(tx.fees)),
                    currency=tx.currency,
                    notes=f"{tx.notes + ' · ' if tx.notes else ''}{origin} · lote {import_batch}",
                    external_id=leg_id,
                )
                inserted_count += 1

            record_audit_event(
                db=db,
                action="IMPORT_BATCH",
                resource_type="transactions",
                after_state={
                    "count": inserted_count,
                    "duplicates_skipped": duplicates_skipped,
                    "import_batch": import_batch,
                    "source_filename": source_filename,
                    "tickers": list({t.ticker for t in transactions}),
                },
            )
            db.commit()
            message = f"Se han importado exitosamente {inserted_count} transacciones"
            if duplicates_skipped:
                message += f" ({duplicates_skipped} duplicada(s) omitida(s))"
            return {
                "success": True,
                "message": message,
                "imported_count": inserted_count,
                "duplicates_skipped": duplicates_skipped,
                "import_batch": import_batch,
            }
        except PortfolioOversellError as exc:
            db.rollback()
            raise ValueError(f"Error de sobreventa en cartera durante la importación: {exc}") from exc
        except Exception:
            db.rollback()
            raise
