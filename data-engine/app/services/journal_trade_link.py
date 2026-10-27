"""Diario de decisiones <-> operaciones reales, con el valor justo del dia.

- ``resolve_trade``: valida que una Transaction es una compra/venta de la misma
  empresa (ValueError con texto en espanol si no).
- ``fair_value_on``: valor justo VIGENTE el dia de la operacion (point-in-time):
  solo cuentan tesis y valoraciones del motor creadas hasta ese dia. Misma
  precedencia que el servicio de valor justo unico: tesis publicada reciente
  (< 180 dias) > motor publicable > tesis publicada antigua > motor orientativo.
- ``journal_entry_payload`` / ``journal_trades``: lo que devuelve la API.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import (
    Company,
    DecisionJournalEntry,
    ThesisVersion,
    Transaction,
    ValuationModel,
    ValuationOutput,
)

TRADE_ACTIONS = ("buy", "sell")
THESIS_MAX_AGE_DAYS = 180
_ACTION_LABELS = {"buy": "Compra", "sell": "Venta"}


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _positive(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(Decimal(str(raw)))
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def resolve_trade(db: Session, company: Company, transaction_id: int) -> Transaction:
    trade = db.scalar(select(Transaction).where(Transaction.id == transaction_id))
    if trade is None:
        raise ValueError("La operación no existe.")
    if trade.company_id != company.id:
        raise ValueError(f"La operación no es de {company.ticker}.")
    if str(trade.action).lower() not in TRADE_ACTIONS:
        raise ValueError("Solo se puede enlazar una compra o venta (no dividendos ni comisiones).")
    return trade


def trade_summary(trade: Transaction) -> dict[str, Any]:
    action = str(trade.action).lower()
    return {
        "id": trade.id,
        "trade_date": trade.trade_date.isoformat(),
        "action": action,
        "action_label": _ACTION_LABELS.get(action, action),
        "quantity": float(trade.quantity) if trade.quantity is not None else None,
        "price": float(trade.price) if trade.price is not None else None,
        "fees": float(trade.fees) if trade.fees is not None else None,
        "currency": trade.currency,
        "source": "IBKR"
        if str(trade.external_id or "").lower().startswith("ibkr")
        or (trade.raw_payload or {}).get("source") == "ibkr"
        else "registro",
    }


def fair_value_on(
    db: Session,
    company: Company,
    day: date,
    *,
    price: Decimal | float | None,
    currency: str | None,
) -> dict[str, Any] | None:
    """Valor justo que habia el dia ``day``; None si no habia ninguno."""
    theses = [
        row
        for row in db.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id, ThesisVersion.status == "published")
            .order_by(desc(ThesisVersion.version))
        ).all()
        if (_as_date(row.created_at) or date.max) <= day and _positive(row.expected_value)
    ]
    thesis = theses[0] if theses else None
    engine_row: tuple[ValuationModel, float] | None = None
    for model in db.scalars(
        select(ValuationModel)
        .where(ValuationModel.company_id == company.id)
        .order_by(desc(ValuationModel.version))
    ).all():
        if (_as_date(model.created_at) or date.max) > day or model.status == "insufficient_data":
            continue
        output = db.scalar(
            select(ValuationOutput).where(ValuationOutput.valuation_model_id == model.id).limit(1)
        )
        value = _positive((output.output_payload or {}).get("expected_value")) if output else None
        if value is not None:
            engine_row = (model, value)
            break

    def from_thesis(row: ThesisVersion, *, stale: bool) -> dict[str, Any]:
        as_of = _as_date(row.created_at)
        return {
            "value": _positive(row.expected_value),
            "source": "tesis",
            "version": row.version,
            "as_of": as_of.isoformat() if as_of else None,
            "stale": stale,
            "label": f"Tesis publicada v{row.version}" + (" (antigua)" if stale else ""),
        }

    def from_engine(model: ValuationModel, value: float) -> dict[str, Any]:
        as_of = _as_date(model.created_at)
        publishable = model.status == "final"
        return {
            "value": value,
            "source": "motor",
            "version": model.version,
            "as_of": as_of.isoformat() if as_of else None,
            "stale": False,
            "label": f"Motor de valoración v{model.version}" + ("" if publishable else " (orientativo)"),
        }

    reading: dict[str, Any] | None = None
    thesis_age = (day - (_as_date(thesis.created_at) or day)).days if thesis else None
    if thesis is not None and thesis_age is not None and thesis_age <= THESIS_MAX_AGE_DAYS:
        reading = from_thesis(thesis, stale=False)
    elif engine_row is not None and engine_row[0].status == "final":
        reading = from_engine(*engine_row)
    elif thesis is not None:
        reading = from_thesis(thesis, stale=True)
    elif engine_row is not None:
        reading = from_engine(*engine_row)
    if reading is None:
        return None

    note = None
    margin = None
    trade_price = _positive(price)
    if trade_price is None:
        note = "Sin precio de ejecución: no se calcula el margen."
    elif currency and company.currency and currency.upper() != company.currency.upper():
        note = (
            f"Operación en {currency.upper()} y valoración en {company.currency.upper()}: "
            "divisa distinta, no se calcula el margen."
        )
    else:
        margin = reading["value"] / trade_price - 1
    reading["margin_vs_trade_price"] = margin
    reading["note"] = note
    return reading


def journal_entry_payload(db: Session, entry: DecisionJournalEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entry.id,
        "thesis_version_id": entry.thesis_version_id,
        "model_version_id": entry.model_version_id,
        "decision_date": entry.decision_date,
        "decision": entry.decision,
        "rationale": entry.rationale,
        "what_must_be_true": entry.what_must_be_true,
        "price": entry.price,
        "status": entry.status,
        "metadata": entry.metadata_,
        "transaction_id": entry.transaction_id,
        "transaction": None,
        "fair_value_on_day": None,
    }
    if entry.transaction_id is None:
        return payload
    trade = db.scalar(select(Transaction).where(Transaction.id == entry.transaction_id))
    company = db.get(Company, entry.company_id)
    if trade is None or company is None:
        return payload
    payload["transaction"] = trade_summary(trade)
    payload["fair_value_on_day"] = fair_value_on(
        db, company, trade.trade_date, price=trade.price, currency=trade.currency
    )
    return payload


def journal_trades(db: Session, company: Company, *, limit: int = 100) -> list[dict[str, Any]]:
    """Compras y ventas de la empresa (mas recientes primero) con sus entradas enlazadas."""
    trades = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.company_id == company.id, Transaction.action.in_(TRADE_ACTIONS))
            .order_by(desc(Transaction.trade_date), desc(Transaction.id))
            .limit(limit)
        ).all()
    )
    linked: dict[int, list[int]] = {}
    if trades:
        for entry in db.scalars(
            select(DecisionJournalEntry).where(
                DecisionJournalEntry.transaction_id.in_([t.id for t in trades])
            )
        ).all():
            if entry.transaction_id is not None:
                linked.setdefault(entry.transaction_id, []).append(entry.id)
    return [{**trade_summary(t), "linked_entry_ids": sorted(linked.get(t.id, []))} for t in trades]
