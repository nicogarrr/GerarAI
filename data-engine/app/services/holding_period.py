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
    # Mismo orden de reproducción que rebuild_position (_replay_order): una
    # venta que solo cabe gracias a una compra posterior del MISMO día se
    # reproduce después de ella. Con el orden bruto de alta, esa tenencia
    # pasaba por negativo y el «Desde» saltaba a la recompra: coste del lote
    # antiguo con antigüedad «nueva» y bucket corto_plazo (medido).
    from app.services.portfolio_ledger_service import _replay_order

    rows_by_company: dict[int, list[Transaction]] = {cid: [] for cid in ids}
    for transaction in db.scalars(
        select(Transaction)
        .where(
            Transaction.company_id.in_(ids),
            func.lower(Transaction.action).in_(["buy", "sell"]),
            *tenant_filters(db, Transaction),
        )
        .order_by(Transaction.trade_date, Transaction.created_at, Transaction.id)
    ).all():
        rows_by_company[int(transaction.company_id)].append(transaction)
    starts: dict[int, date] = {}
    for cid, rows in rows_by_company.items():
        held = Decimal("0")
        for transaction in _replay_order(rows):
            qty = Decimal(str(transaction.quantity))
            if str(transaction.action).lower() == "buy":
                if held <= 0:
                    starts[cid] = transaction.trade_date
                held += qty
            else:
                held -= qty
    return starts
