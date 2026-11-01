"""Inicio de la tenencia actual de cada posición (para «Desde» y la antigüedad).

La primera compra registrada del ticker no vale: si la posición se vendió
entera y se volvió a comprar, la tenencia actual empieza en la nueva compra.
Se reproduce el ledger compra/venta en el mismo orden que rebuild_position.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Transaction


def current_holding_starts(db: Session, company_ids: Iterable[int]) -> dict[int, date]:
    """Fecha de la compra que abrió la tenencia actual, por compañía (una query)."""
    ids = set(company_ids)
    if not ids:
        return {}
    starts: dict[int, date] = {}
    held: dict[int, Decimal] = {}
    for company_id, trade_date, action, quantity in db.execute(
        select(Transaction.company_id, Transaction.trade_date, Transaction.action, Transaction.quantity)
        .where(
            Transaction.company_id.in_(ids),
            func.lower(Transaction.action).in_(["buy", "sell"]),
            *tenant_filters(db, Transaction),
        )
        .order_by(Transaction.trade_date, Transaction.created_at, Transaction.id)
    ).all():
        cid = int(company_id)
        qty = Decimal(str(quantity))
        before = held.get(cid, Decimal("0"))
        if str(action).lower() == "buy":
            if before <= 0:
                starts[cid] = trade_date
            held[cid] = before + qty
        else:
            held[cid] = before - qty
    return starts
