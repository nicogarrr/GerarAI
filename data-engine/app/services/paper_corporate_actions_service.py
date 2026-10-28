"""Dividendos y splits del paper book, con fuente y sin reescribir la historia.

Dividendos: se leen DividendRecord ya ingeridos (Yahoo, FMP de respaldo; cada
fila con fuente y fetched_at) en la ventana (entrada, hasta]. Los grupos Yahoo
ambiguos (misma fecha ex, importes distintos) son INCIERTOS y se excluyen con
la misma regla del resto de la app (`resolve_yahoo_events`). Un dividendo en
otra divisa que el trade nunca se convierte: se ignora y se cuenta. Los largos
cobran, los cortos pagan.

Splits: las posiciones ABIERTAS se ajustan (cantidad x ratio, niveles / ratio)
con auditoria por trade (ids aplicados, contador, ultima accion con fuente).
Una propuesta PENDIENTE con split posterior a su creacion NO rellena: sus
niveles pre-split no son comparables con cotizaciones post-split, asi que se
marca con aviso y queda fuera de los fills. Un trade CERRADO jamas se
reescribe: se marca con aviso y el scoreboard lo excluye del hit-rate.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import Company, CorporateAction, DividendRecord
from app.models.paper_trading import PaperTrade
from app.services.dividend_records import resolve_yahoo_events

SPLIT_TYPES = ("split", "reverse_split")
PENDING_SPLIT_WARNING = "split_pendiente_sin_ajustar"
CLOSED_SPLIT_WARNING = "split_cerrado_sin_ajustar"
DIVIDEND_SOURCE = "Yahoo Finance chart/dividends (fallback FMP stable/dividends), via DividendRecord"
_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class DividendAccrual:
    total: Decimal  # efecto firmado en el P&L: + largo, - corto
    count: int
    uncertain: int  # eventos Yahoo ambiguos excluidos
    wrong_currency: int  # eventos en otra divisa, ignorados (nunca se convierten)


def _day(value: datetime) -> date:
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).date()


def _company(db: Session, ticker: str) -> Company | None:
    return db.scalar(select(Company).where(Company.ticker == ticker))


def accrued_dividends(db: Session, row: PaperTrade, *, until: date) -> DividendAccrual | None:
    """Dividendos declarados con ex_date en (entrada, hasta]. None si no computable."""
    if row.entry_at is None or row.currency is None:
        return None
    company = _company(db, row.ticker)
    if company is None:
        return None
    records = db.scalars(
        select(DividendRecord).where(
            DividendRecord.company_id == company.id,
            DividendRecord.ex_date > _day(row.entry_at),
            DividendRecord.ex_date <= until,
            *tenant_filters(db, DividendRecord),
        )
    ).all()
    kept, uncertain = resolve_yahoo_events(records)
    sign = Decimal(1) if row.direction == "long" else Decimal(-1)
    total, count, wrong_currency = Decimal(0), 0, 0
    for record in kept:
        if record.currency != row.currency:
            wrong_currency += 1
            continue
        total += record.amount * row.quantity * sign
        count += 1
    return DividendAccrual(total, count, len(uncertain), wrong_currency)


def sync_dividends(db: Session, row: PaperTrade) -> bool:
    """Persiste el devengo de dividendos del trade (idempotente, recomputa)."""
    if row.entry_at is None:
        return False
    until = _day(row.exit_at) if row.status == "closed" and row.exit_at is not None else datetime.now(UTC).date()
    accrual = accrued_dividends(db, row, until=until)
    if accrual is None:
        return False
    changed = (
        row.dividends_total != accrual.total
        or row.dividends_count != accrual.count
        or row.dividends_uncertain != accrual.uncertain
        or row.dividends_wrong_currency != accrual.wrong_currency
    )
    row.dividends_total = accrual.total
    row.dividends_count = accrual.count
    row.dividends_uncertain = accrual.uncertain
    row.dividends_wrong_currency = accrual.wrong_currency
    if accrual.count or accrual.uncertain or accrual.wrong_currency:
        row.dividends_source = DIVIDEND_SOURCE
    return changed


def _applied_ids(row: PaperTrade) -> set[int]:
    return {int(x) for x in (row.applied_split_ids or "").split(",") if x.strip().isdigit()}


def sync_corporate_actions(db: Session, row: PaperTrade) -> bool:
    """Aplica/marca los splits declarados posteriores a la entrada o propuesta."""
    company = _company(db, row.ticker)
    if company is None:
        return False
    anchor = row.entry_at or row.created_at
    actions = db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.company_id == company.id,
            CorporateAction.action_type.in_(SPLIT_TYPES),
            CorporateAction.effective_date > _day(anchor),
            *tenant_filters(db, CorporateAction),
        )
        .order_by(CorporateAction.effective_date, CorporateAction.id)
    ).all()
    if not actions:
        return False
    done = _applied_ids(row)
    pending = [a for a in actions if a.id not in done]
    if not pending:
        return False
    if row.status == "closed":
        # En (entrada, salida] o ingerido tarde: nunca se reescribe el cierre.
        if not row.corporate_action_warning:
            row.corporate_action_warning = CLOSED_SPLIT_WARNING
            row.last_corporate_action = _note(pending[-1])
            return True
        return False
    if row.status == "pending":
        row.corporate_action_warning = PENDING_SPLIT_WARNING
        row.last_corporate_action = _note(pending[-1])
        return True
    for action in pending:
        ratio = Decimal(action.ratio)
        if not ratio.is_finite() or ratio <= 0:
            continue
        row.quantity = (row.quantity * ratio).quantize(_QUANTUM, rounding=ROUND_HALF_UP)
        for field in ("entry_price", "stop", "target"):
            value = getattr(row, field)
            if value is not None:
                setattr(row, field, (value / ratio).quantize(_QUANTUM, rounding=ROUND_HALF_UP))
        done.add(action.id)
        row.split_adjustments = (row.split_adjustments or 0) + 1
        row.last_corporate_action = _note(action)
    row.applied_split_ids = ",".join(str(i) for i in sorted(done))
    return True


def _note(action: CorporateAction) -> str:
    return f"{action.action_type} {action.effective_date} x{action.ratio} (fuente: {action.source})"
