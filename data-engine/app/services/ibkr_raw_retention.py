"""Retención de ``ibkr_raw_rows`` (auditoría A7).

Cada Flex diario reescribe las secciones de FOTO (posiciones abiertas, caja,
tipos de cambio, NAV...) con su fecha de informe: cada día son filas nuevas
(hash distinto) y la tabla crecía sin límite. Las secciones de EVENTOS
(operaciones, dividendos, acciones corporativas) aparecen una vez y se
guardan siempre: son la evidencia del ledger.

Política: se borran solo filas de foto con ``report_date`` anterior a
``keep_days`` (por defecto 400 días: un ejercicio fiscal completo más margen,
y más de lo que IBKR deja volver a descargar por Flex). Nunca se borra la foto
de la fecha que fijó el coste de una posición abierta (la conciliación de
costes la lee) ni una fila sin fecha. ``keep_days <= 0`` desactiva la poda.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.core.tenancy import tenant_filters
from app.models import IbkrRawRow, Position

SNAPSHOT_SECTIONS = frozenset({
    "OpenPositions",
    "CashReport",
    "EquitySummaryInBase",
    "ConversionRates",
    "NetStockPositionSummary",
    "ChangeInNAV",
    "ChangeInPositionValues",
    "MTMPerformanceSummaryInBase",
    "FIFOPerformanceSummaryInBase",
    "PriorPeriodPositions",
})


def prune_ibkr_raw_rows(db: Session, *, keep_days: int, today: date | None = None) -> int:
    """Borra filas de foto antiguas del tenant actual; devuelve cuántas."""
    if keep_days <= 0:
        return 0
    cutoff = (today or local_today()) - timedelta(days=keep_days)
    protected = {
        position.statement_as_of or position.as_of
        for position in db.scalars(select(Position).where(*tenant_filters(db, Position)))
    }
    protected.discard(None)
    conditions = [
        *tenant_filters(db, IbkrRawRow),
        IbkrRawRow.section.in_(SNAPSHOT_SECTIONS),
        IbkrRawRow.report_date.is_not(None),
        IbkrRawRow.report_date < cutoff,
    ]
    if protected:
        conditions.append(IbkrRawRow.report_date.not_in(protected))
    result = db.execute(
        delete(IbkrRawRow).where(*conditions),
        execution_options={"synchronize_session": False},
    )
    return int(result.rowcount or 0)
