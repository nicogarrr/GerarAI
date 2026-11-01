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

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import (
    Company,
    DecisionJournalEntry,
    ThesisVersion,
    Transaction,
    ValuationModel,
    ValuationOutput,
)
from app.schemas.api import valuation_uses_inferred_inputs
from app.services.fair_value_service import listed_value
from app.valuation.currency import normalize_currency

logger = logging.getLogger(__name__)

TRADE_ACTIONS = ("buy", "sell")
# Decision del diario -> accion de la operacion que la ejecutaria. «hold»,
# «watch» y «avoid» no tienen operacion: nunca se enlazan.
DECISION_TRADE_ACTION = {"buy": "buy", "sell": "sell", "trim": "sell"}
# Ventana (dias) DESPUES de la fecha de la decision en la que una operacion se
# considera candidata. HIPOTESIS de producto sin confirmar: la operacion debe
# ser del mismo dia o posterior (la decision precede a la ejecucion; una compra
# anterior pudo responder a otro razonamiento) y a <= 3 dias.
# Conservador por defecto: un candidato unico se SUGIERE (status "suggested") y el usuario lo
# confirma; fecha/lado/moneda/precio no bastan para fijar el vinculo (faltan cantidad/cuenta/hora).
AUTO_LINK_WINDOW_DAYS = 3
# Veto por precio: si la entrada guarda un precio y esta en la misma divisa que
# la operacion, una diferencia relativa mayor que esta no es candidata. El
# diario NO guarda cantidad, cuenta ni hora: no se infieren.
AUTO_LINK_MAX_PRICE_GAP = Decimal("0.25")
THESIS_MAX_AGE_DAYS = 180
_ACTION_LABELS = {"buy": "Compra", "sell": "Venta"}


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _known_on(row: ThesisVersion | ValuationModel, day: date) -> bool:
    """The current mutable revision must already have existed on the trade day.

    A draft can be published or recalculated in place after creation. Without
    revision history we cannot reconstruct its old value, so omit that row.
    """
    created = _as_date(row.created_at)
    updated = _as_date(row.updated_at)
    return created is not None and created <= day and (updated is None or updated <= day)


def _positive(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(Decimal(str(raw)))
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def _unit_factor(trade_currency: str | None, company_currency: str | None) -> float | None:
    """Factor exacto de la unidad de la operacion a la de la empresa.

    Misma divisa principal: «GBp» (peniques) frente a «GBP» es 1/100, no 1
    (``.upper()`` igualaba las dos y el margen salia con 2.650 p contra 30 £).
    Otra divisa principal o desconocida: None (no se compara).
    """
    trade_major, trade_divisor = normalize_currency(trade_currency)
    company_major, company_divisor = normalize_currency(company_currency)
    if not trade_major or trade_major != company_major:
        return None
    return company_divisor / trade_divisor


def resolve_trade(db: Session, company: Company, transaction_id: int) -> Transaction:
    trade = db.scalar(select(Transaction).where(Transaction.id == transaction_id))
    if trade is None:
        raise ValueError("La operación no existe.")
    if trade.company_id != company.id:
        raise ValueError(f"La operación no es de {company.ticker}.")
    if str(trade.action).lower() not in TRADE_ACTIONS:
        raise ValueError("Solo se puede enlazar una compra o venta (no dividendos ni comisiones).")
    return trade


def resolve_decision_trade(
    db: Session, company: Company, transaction_id: int, decision: str,
) -> Transaction:
    """An execution must match the decision's side, not merely its ticker."""
    expected = DECISION_TRADE_ACTION.get(decision)
    if expected is None:
        raise ValueError("Esta decisión no admite una operación de compra o venta.")
    trade = resolve_trade(db, company, transaction_id)
    if str(trade.action).lower() != expected:
        raise ValueError("La operación debe ser del mismo sentido que la decisión (compra o venta).")
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


def _thesis_value(row: ThesisVersion) -> float | None:
    """Valor de la tesis por acción COTIZADA (ADR: ``listed_share_values``)."""
    basis = row.valuation_basis if isinstance(row.valuation_basis, dict) else {}
    return listed_value(basis, fallback={"expected_value": row.expected_value})


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
        if _known_on(row, day)
        and _thesis_value(row) is not None
        and not valuation_uses_inferred_inputs(row.valuation_basis)
    ]
    thesis = theses[0] if theses else None
    engine_row: tuple[ValuationModel, float] | None = None
    for model in db.scalars(
        select(ValuationModel)
        .where(ValuationModel.company_id == company.id)
        .order_by(desc(ValuationModel.version))
    ).all():
        if not _known_on(model, day) or model.status not in ("final", "draft"):
            continue
        output = db.scalar(
            select(ValuationOutput).where(ValuationOutput.valuation_model_id == model.id).limit(1)
        )
        payload = output.output_payload if output and isinstance(output.output_payload, dict) else None
        # Valor por acción COTIZADA: un ADR se compara con su valor por ADR.
        value = listed_value(payload, fallback=payload) if payload else None
        if value is not None:
            engine_row = (model, value)
            break

    def from_thesis(row: ThesisVersion, *, stale: bool) -> dict[str, Any]:
        as_of = _as_date(row.created_at)
        return {
            "value": _thesis_value(row),
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
    elif not currency or not company.currency:
        note = "Divisa desconocida: no se calcula el margen."
    elif (to_company := _unit_factor(currency, company.currency)) is None:
        note = (
            f"Operación en {currency.upper()} y valoración en {company.currency.upper()}: "
            "divisa distinta, no se calcula el margen."
        )
    else:
        margin = reading["value"] / (trade_price * to_company) - 1
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


def _price_compatible(
    entry: DecisionJournalEntry, trade: Transaction, company_currency: str | None
) -> bool:
    """False solo si hay dos precios comparables (misma divisa) y difieren demasiado."""
    decision_price = _positive(entry.price)
    trade_price = _positive(trade.price)
    if decision_price is None or trade_price is None:
        return True
    to_company = _unit_factor(trade.currency, company_currency) if company_currency else None
    if to_company is None:
        return True
    return abs(trade_price * to_company / decision_price - 1) <= float(AUTO_LINK_MAX_PRICE_GAP)


def auto_link_journal_trades(
    db: Session, company_ids: set[int] | None = None
) -> dict[str, int]:
    """Detecta candidatas; nunca confirma por heuristica una asociacion historica.

    Una decision sin operacion (``transaction_id`` nulo) de compra/venta/reduccion
    recibe una sugerencia de compra/venta de la misma empresa cuando:
    - la accion coincide (buy->buy, sell/trim->sell),
    - la operacion es del mismo dia que la decision o hasta ``AUTO_LINK_WINDOW_DAYS``
      despues (una operacion anterior pudo responder a otro razonamiento),
    - el precio, si ambos existen y estan en la misma divisa, no difiere > 25 %,
    - la operacion no esta ya enlazada a otra entrada,
    - y la relacion es uno a uno: esa entrada tiene UNA sola candidata y esa
      operacion tiene UNA sola entrada candidata.
    Si hay varias posibles (p. ej. ejecuciones parciales o dos decisiones el
    mismo dia) no se asigna nada: la entrada queda marcada
    ``metadata.auto_link = {"status": "ambiguous", "candidate_transaction_ids": [...]}``
    para que el usuario elija. No toca la fecha ni el precio de la decision ni
    crea ni envia ordenes. Una entrada que el usuario desenlazo a mano
    (``metadata.auto_link.status == "user_unlinked"``) no se vuelve a enlazar.
    Idempotente.
    """
    summary = {"linked": 0, "ambiguous": 0, "unlinked": 0, "suggested": 0}
    query = select(DecisionJournalEntry).where(
        DecisionJournalEntry.decision.in_(list(DECISION_TRADE_ACTION)),
    )
    if company_ids is not None:
        if not company_ids:
            return summary
        query = query.where(DecisionJournalEntry.company_id.in_(company_ids))
    all_entries = list(db.scalars(query).all())

    def _meta(entry: DecisionJournalEntry) -> dict[str, Any]:
        return dict(entry.metadata_ or {})

    def _is_auto(entry: DecisionJournalEntry) -> bool:
        link = _meta(entry).get("auto_link") or {}
        return (
            entry.transaction_id is not None
            and link.get("status") == "linked"
            and link.get("transaction_id") == entry.transaction_id
        )

    # Entradas a evaluar: las pendientes y las enlazadas AUTOMATICAMENTE (que se
    # reevaluan ante cada operacion nueva). Los enlaces manuales/confirmados no se tocan.
    entries = [
        entry
        for entry in all_entries
        if _is_auto(entry)
        or (
            entry.transaction_id is None
            and (_meta(entry).get("auto_link") or {}).get("status") != "user_unlinked"
        )
    ]
    if not entries:
        return summary
    auto_ids = {entry.id for entry in entries if _is_auto(entry)}
    company_set = {entry.company_id for entry in entries}
    trades = list(
        db.scalars(
            select(Transaction).where(
                Transaction.company_id.in_(company_set),
                Transaction.action.in_(TRADE_ACTIONS),
            )
        ).all()
    )
    # Operaciones ya ligadas por el usuario (o por otra entrada no automatica).
    already_linked = {
        entry.transaction_id
        for entry in all_entries
        if entry.transaction_id is not None and entry.id not in auto_ids
    } | {
        tid
        for tid in db.scalars(
            select(DecisionJournalEntry.transaction_id).where(
                *tenant_filters(db, DecisionJournalEntry),
                DecisionJournalEntry.transaction_id.is_not(None),
                DecisionJournalEntry.decision.notin_(list(DECISION_TRADE_ACTION)),
            )
        ).all()
    }
    window = AUTO_LINK_WINDOW_DAYS
    company_currency = {
        company.id: company.currency
        for company in db.scalars(select(Company).where(Company.id.in_(company_set))).all()
    }
    candidates: dict[int, list[Transaction]] = {}
    for entry in entries:
        wanted = DECISION_TRADE_ACTION[entry.decision]
        decided = _as_date(entry.decision_date)
        candidates[entry.id] = (
            []
            if decided is None
            else [
                trade
                for trade in trades
                if trade.company_id == entry.company_id
                and str(trade.action).lower() == wanted
                and trade.id not in already_linked
                and 0 <= (trade.trade_date - decided).days <= window
                and _price_compatible(entry, trade, company_currency.get(entry.company_id))
            ]
        )
    entries_by_trade: dict[int, int] = {}
    for found in candidates.values():
        for trade in found:
            entries_by_trade[trade.id] = entries_by_trade.get(trade.id, 0) + 1
    now = datetime.now(UTC).isoformat()
    for entry in entries:
        found = candidates[entry.id]
        meta = _meta(entry)
        unique = len(found) == 1 and entries_by_trade[found[0].id] == 1
        ambiguous = len(found) > 1 or (bool(found) and entries_by_trade[found[0].id] > 1)
        if _is_auto(entry):
            # Un enlace heuristico anterior tampoco equivale a confirmacion del usuario.
            entry.transaction_id = None
            summary["unlinked"] += 1
        if unique:
            previous = meta.get("auto_link") or {}
            if previous.get("status") != "suggested" or previous.get("candidate_transaction_id") != found[0].id:
                meta["auto_link"] = {"status": "suggested", "candidate_transaction_id": found[0].id, "at": now}
                entry.metadata_ = meta
            summary["suggested"] += 1
        elif ambiguous:
            ids = sorted(trade.id for trade in found)
            previous = meta.get("auto_link") or {}
            if previous.get("status") != "ambiguous" or previous.get("candidate_transaction_ids") != ids:
                meta["auto_link"] = {"status": "ambiguous", "candidate_transaction_ids": ids, "at": now}
                entry.metadata_ = meta
            summary["ambiguous"] += 1
        elif (meta.get("auto_link") or {}).get("status") in ("ambiguous", "suggested", "linked"):
            # Ya no hay candidatas (fechas editadas, importacion corregida...): se limpia
            # la marca para no ofrecer candidatas obsoletas.
            meta.pop("auto_link", None)
            entry.metadata_ = meta
    return summary


def auto_link_journal_trades_best_effort(
    db: Session, company_ids: set[int] | None = None
) -> dict[str, int] | None:
    """Tras una importacion/operacion ya confirmada: nunca la rompe ni la revierte."""
    try:
        summary = auto_link_journal_trades(db, company_ids)
        db.commit()
        return summary
    except Exception:  # noqa: BLE001 - el enlace es accesorio; el commit previo ya esta hecho
        db.rollback()
        logger.warning("auto_link_journal_trades failed", exc_info=True)
        return None
