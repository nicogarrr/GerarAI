"""Backfill historico del libro de operaciones desde IBKR Flex (solo Trades).

El sync diario pide el extracto sin fechas y la query devuelve su periodo por
defecto (el ultimo dia habil): el libro solo cubre desde que se activo. IBKR
admite ``fd``/``td`` (yyyyMMdd, maximo 366 dias, ``td`` un dia habil ya cerrado).
Este modulo trocea el rango y delega en ``IBKRImportService.import_flex_xml`` con
``trades_only=True``: idempotente por trade id, sin tocar posiciones, caja ni
snapshots.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.services.connectors.ibkr import IBKRFlexClient
from app.services.ibkr_import_service import IBKRImportService

MAX_RANGE_DAYS = 360  # margen bajo el limite de 366 dias de IBKR


def split_ranges(from_date: date, to_date: date, max_days: int = MAX_RANGE_DAYS) -> list[tuple[date, date]]:
    if to_date < from_date:
        raise ValueError("to_date must not be before from_date")
    ranges: list[tuple[date, date]] = []
    start = from_date
    while start <= to_date:
        end = min(start + timedelta(days=max_days - 1), to_date)
        ranges.append((start, end))
        start = end + timedelta(days=1)
    return ranges


async def backfill_trades(
    db: Session,
    from_date: date,
    to_date: date,
    *,
    dry_run: bool = True,
    only_existing_companies: bool = True,
    include_cash_income: bool = False,
    client: IBKRFlexClient | None = None,
) -> list[dict[str, Any]]:
    """Importa (o simula) los trades de ``from_date``..``to_date`` por tramos."""
    client = client or IBKRFlexClient()
    results: list[dict[str, Any]] = []
    for start, end in split_ranges(from_date, to_date):
        xml = await client.fetch_range_xml(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        result = IBKRImportService().import_flex_xml(
            db,
            xml,
            trades_only=True,
            dry_run=dry_run,
            only_existing_companies=only_existing_companies,
            include_cash_income=include_cash_income,
        )
        results.append({"from": start.isoformat(), "to": end.isoformat(), **result})
    return results
