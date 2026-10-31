"""Reparto de la aportacion mensual del plan ponderado por nivel DCA.

«Este mes 225,00 EUR a POOL, 75,00 EUR a UBER». La cuota del plan se reparte
entre sus tickers:

- Base ``objetivos_ticker``: los objetivos del plan de tipo ``ticker`` (su
  ``target_pct`` es el peso base). Los objetivos por sector o clase de activo
  no son destinos de compra y no entran.
- Base ``posiciones_iguales``: sin objetivos por ticker, las posiciones vivas
  (cantidad > 0) a partes iguales.

Cada peso base se multiplica por el nivel DCA del motor (``dca_signal_states``):
4X pesa 4, 3X 3, 2X 2, 1X 1 y las zonas de recorte (-1/-2) pesan 0: no se
aporta dinero nuevo a un valor que el motor manda recortar.

Degrada limpio: si la tabla ``dca_signal_states`` no existe (el motor DCA aun
no esta desplegado) o un ticker no tiene nivel, ese ticker pesa como 1X y la
respuesta lo dice; nunca se inventa un nivel. Si todo esta en recorte, la
cuota queda sin asignar (liquidez) y se dice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import Company, Position
from app.services.investment_plan_service import InvestmentPlanService

DCA_TABLE = "dca_signal_states"
DCA_MULTIPLIER: dict[int, int] = {4: 4, 3: 3, 2: 2, 1: 1, -1: 0, -2: 0}
DCA_LABELS: dict[int, str] = {
    4: "4X DCA",
    3: "3X DCA",
    2: "2X DCA",
    1: "1X DCA",
    -1: "RECORTE LIGERO",
    -2: "RECORTE FUERTE",
}
_CENT = Decimal("0.01")
# Un nivel DCA vale para el mes en formacion o el ultimo confirmado. Uno mas
# viejo (ticker que dejo de evaluarse, motor parado) no dice nada de este mes.
DCA_MAX_AGE_MONTHS = 1


def _today() -> date:
    # Mes del usuario (Europe/Madrid): el servidor corre en UTC.
    return local_today()


def _months_old(period: str | None, today: date) -> int | None:
    """Meses entre ``period`` (YYYY-MM) y el mes de ``today``; None si no se puede leer."""
    try:
        year, month = (int(part) for part in str(period).split("-")[:2])
    except (TypeError, ValueError):
        return None
    if not 1 <= month <= 12:
        return None
    return (today.year - year) * 12 + (today.month - month)


@dataclass(frozen=True)
class SplitCandidate:
    ticker: str
    base_weight: Decimal
    dca_level: int | None = None
    dca_period: str | None = None
    dca_status: str | None = None
    dca_stale: bool = False


def _money_es(value: Decimal) -> str:
    """225.5 -> «225,50» (miles con punto)."""
    text = f"{value.quantize(_CENT, rounding=ROUND_HALF_UP):,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _multiplier(level: int | None) -> int:
    if level is None:
        return 1
    return DCA_MULTIPLIER.get(int(level), 1)


def _reason(candidate: SplitCandidate) -> str:
    level = candidate.dca_level
    if candidate.dca_stale:
        return f"nivel DCA caducado (mes {candidate.dca_period or 's/d'}): peso normal (1X) hasta reevaluar"
    if level is None:
        return "sin nivel DCA: peso normal (1X)"
    label = DCA_LABELS.get(int(level), f"nivel {level}")
    if _multiplier(level) == 0:
        return f"{label}: zona de recorte, este mes no recibe aportación"
    return f"{label}: peso ×{_multiplier(level)}"


def split_contribution(amount: Decimal, candidates: list[SplitCandidate]) -> dict[str, Any]:
    """Reparto puro: importes al centimo y la suma cuadra con ``amount``."""
    amount = Decimal(amount).quantize(_CENT, rounding=ROUND_HALF_UP)
    effective = [
        (candidate, max(Decimal(candidate.base_weight), Decimal(0)) * _multiplier(candidate.dca_level))
        for candidate in candidates
    ]
    total_weight = sum((weight for _, weight in effective), Decimal(0))
    amounts: list[Decimal] = []
    if total_weight > 0:
        amounts = [
            (amount * weight / total_weight).quantize(_CENT, rounding=ROUND_HALF_UP)
            for _, weight in effective
        ]
        residual = amount - sum(amounts, Decimal(0))
        if residual and amounts:
            # El centimo que sobra o falta va al de mayor peso (el ultimo en empate).
            biggest = max(range(len(effective)), key=lambda i: (effective[i][1], i))
            amounts[biggest] += residual
    else:
        amounts = [Decimal(0) for _ in effective]

    allocations = []
    for (candidate, weight), value in zip(effective, amounts, strict=True):
        share = (weight / total_weight * 100) if total_weight > 0 else Decimal(0)
        allocations.append(
            {
                "ticker": candidate.ticker,
                "amount": float(value),
                "share_pct": float(share.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
                "base_weight": float(candidate.base_weight),
                "dca_level": candidate.dca_level,
                "dca_label": DCA_LABELS.get(int(candidate.dca_level))
                if candidate.dca_level is not None
                else None,
                "dca_period": candidate.dca_period,
                "dca_status": candidate.dca_status,
                "dca_stale": candidate.dca_stale,
                "multiplier": _multiplier(candidate.dca_level),
                "reason": _reason(candidate),
            }
        )
    if not candidates:
        status = "no_candidates"
    elif total_weight <= 0:
        status = "all_trim"
    else:
        status = "ok"
    allocated = sum(amounts, Decimal(0))
    return {
        "status": status,
        "allocations": allocations,
        "unallocated": float(amount - allocated),
    }


def dca_table_available(db: Session) -> bool:
    try:
        return inspect(db.get_bind()).has_table(DCA_TABLE)
    except Exception:  # noqa: BLE001 - sin tabla legible = sin nivel DCA, nunca rompe el plan
        return False


def _dca_rows(db: Session) -> list[Any] | None:
    """Filas de ``dca_signal_states`` del tenant; None si el motor no esta desplegado."""
    if not dca_table_available(db):
        return None
    table = sa.table(
        DCA_TABLE,
        sa.column("id"),
        sa.column("tenant_id"),
        sa.column("symbol"),
        sa.column("company_id"),
        sa.column("level"),
        sa.column("status"),
        sa.column("period"),
    )
    statement = select(
        table.c.id, table.c.symbol, table.c.company_id, table.c.level, table.c.status, table.c.period
    )
    tenant_id = db.info.get("tenant_id")
    if tenant_id is not None:
        statement = statement.where(table.c.tenant_id == tenant_id)
    try:
        return list(db.execute(statement).all())
    except Exception:  # noqa: BLE001 - esquema distinto al esperado: se degrada a "sin nivel"
        return None


def build_contribution_split(db: Session) -> dict[str, Any]:
    service = InvestmentPlanService()
    plan = service.get_plan(db)
    if plan is None:
        return {"plan_exists": False}

    currency = (plan.monthly_contribution_currency or "").upper() or None
    notes: list[str] = []
    ticker_targets = [
        target
        for target in (plan.target_allocations or [])
        if target.get("kind") == "ticker"
        and str(target.get("label") or "").strip()
        and Decimal(str(target.get("target_pct") or 0)) > 0
    ]
    if ticker_targets:
        basis = "objetivos_ticker"
        weights: dict[str, Decimal] = {}
        for target in ticker_targets:
            ticker = str(target["label"]).strip().upper()
            weights[ticker] = weights.get(ticker, Decimal(0)) + Decimal(str(target["target_pct"]))
        companies = {
            company.ticker.upper(): company
            for company in db.scalars(select(Company).where(Company.ticker.in_(list(weights)))).all()
        }
    else:
        basis = "posiciones_iguales"
        rows = db.execute(
            select(Position, Company)
            .join(Company, Position.company_id == Company.id)
            .where(Position.quantity > 0)
        ).all()
        companies = {}
        for _, company in rows:
            companies.setdefault(company.ticker.upper(), company)
        weights = {ticker: Decimal(1) for ticker in companies}
        if weights:
            notes.append(
                "El plan no tiene objetivos por ticker: se reparte a partes iguales entre las posiciones vivas."
            )

    dca_rows = _dca_rows(db)
    dca_available = dca_rows is not None
    by_company = {row.company_id: row for row in dca_rows or [] if row.company_id is not None}
    by_symbol = {str(row.symbol).upper(): row for row in dca_rows or []}
    if not dca_available:
        notes.append(
            "El motor DCA no está desplegado todavía: el reparto sigue solo los pesos del plan (todos como 1X)."
        )

    today = _today()
    candidates: list[SplitCandidate] = []
    for ticker, weight in weights.items():
        company = companies.get(ticker)
        row = (by_company.get(company.id) if company else None) or by_symbol.get(ticker)
        level = int(row.level) if row is not None and row.level is not None else None
        period = str(row.period) if row is not None and row.period is not None else None
        stale = False
        if level is not None:
            age = _months_old(period, today)
            # Sin mes legible, EN EL FUTURO (dato corrupto: ese mes aun no se
            # puede haber evaluado) o de hace mas de un mes: no se usa (1X).
            stale = age is None or age < 0 or age > DCA_MAX_AGE_MONTHS
        candidates.append(
            SplitCandidate(
                ticker=ticker,
                base_weight=weight,
                dca_level=None if stale else level,
                dca_period=period,
                dca_status=str(row.status) if row is not None and row.status is not None else None,
                dca_stale=stale,
            )
        )
    stale_tickers = [c.ticker for c in candidates if c.dca_stale]
    if stale_tickers:
        notes.append(
            "Nivel DCA de hace más de un mes en "
            + ", ".join(stale_tickers)
            + ": pesa como 1X hasta que se vuelva a evaluar."
        )
    if dca_available and candidates and all(c.dca_level is None and not c.dca_stale for c in candidates):
        notes.append("Ningún ticker del plan tiene nivel DCA calculado: todos pesan como 1X.")

    amount = Decimal(plan.monthly_contribution)
    result = split_contribution(amount, candidates)
    unit = f" {currency}" if currency else ""
    summary = None
    funded = [row for row in result["allocations"] if row["amount"] > 0]
    if result["status"] == "ok" and funded:
        parts = [f"{_money_es(Decimal(str(row['amount'])))}{unit} a {row['ticker']}" for row in funded]
        summary = "Este mes " + ", ".join(parts)
    elif result["status"] == "all_trim":
        summary = (
            f"Este mes todo el plan está en zona de recorte: los {_money_es(amount)}{unit} "
            "quedan en liquidez."
        )
    if currency is None:
        notes.append("La divisa de la aportación no está registrada en el plan.")
    from app.services.savings_projection import savings_contract

    return {
        "savings_projection": savings_contract(db),
        "plan_exists": True,
        "amount": float(amount),
        "currency": currency,
        "basis": basis,
        "dca_available": dca_available,
        "summary": summary,
        "notes": notes,
        **result,
    }
