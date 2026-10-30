"""Simulación FIFO de la venta de una posición, para el IRPF del Cerebro.

Art. 37.2 LIRPF (valores homogéneos): se venden primero las acciones
compradas antes. El simulador del chat usaba el coste medio de la posición,
que con compras a precios distintos da otra ganancia: con 10 a 100 € y 10 a
200 €, vender 10 a 180 € es una ganancia FIFO de 800 € y no de 300 €.

Los lotes salen de las compras guardadas (fecha, cantidad, precio y
comisiones) y las ventas ya hechas consumen los lotes más antiguos antes de
simular la nueva. El coste en euros que muestra el Cerebro sigue el criterio
del informe fiscal (DGT V0152-26): coste en la divisa del valor al cambio de
la FECHA DE VENTA (``cost_eur_dgt``); ``cost_eur`` (cambio de compra) queda
solo para lotes en una divisa distinta de la de venta.

Regla de los dos meses (art. 33.5.f LIRPF): una pérdida no se computa si se
compraron valores homogéneos en los dos meses anteriores a la venta y siguen
en cartera después de ella. Se calcula con los lotes que quedan tras la venta
FIFO.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.services.tax_report_service import (
    BUY_ACTIONS,
    MAX_FX_AGE_DAYS,
    SELL_ACTIONS,
    WASH_SALE_WINDOW,
    _fifo_sort_key,
    _rate_not_older_than,
    backward_repurchase_quantity,
    replay_tax_fifo,
)

TAX_CURRENCY = "EUR"


@dataclass
class ConsumedLot:
    #: None solo en una venta hipotética con lotes sin fecha (orden dado).
    trade_date: date | None
    quantity: Decimal
    unit_cost_eur: Decimal | None
    unit_cost_native: Decimal
    currency: str

    @property
    def cost_eur(self) -> Decimal | None:
        return None if self.unit_cost_eur is None else self.unit_cost_eur * self.quantity

    def cost_eur_dgt(self, sale_currency: str, sale_rate: Decimal | None) -> Decimal | None:
        """Coste en euros con el criterio del informe fiscal (DGT V0152-26).

        La ganancia se calcula en la divisa del valor y se pasa a euros al
        cambio de la FECHA DE VENTA: el coste nativo (con su diferido) va al
        cambio de la venta, no al de la compra. Un lote en otra divisa que la
        de la venta (dato raro) conserva su coste al cambio de compra.
        """
        native = self.unit_cost_native * self.quantity
        if (self.currency or TAX_CURRENCY) == TAX_CURRENCY:
            return native
        if self.currency == sale_currency:
            return None if sale_rate is None else native * sale_rate
        return self.cost_eur


@dataclass
class FifoSale:
    quantity: Decimal
    lots: list[ConsumedLot] = field(default_factory=list)
    #: Acciones que siguen en cartera tras la venta y se compraron en los dos
    #: meses anteriores: bloquean una pérdida por esa cantidad.
    blocking_qty: Decimal = Decimal("0")
    blocking_dates: list[date] = field(default_factory=list)

    @property
    def cost_eur(self) -> Decimal | None:
        total = Decimal("0")
        for lot in self.lots:
            if lot.cost_eur is None:
                return None
            total += lot.cost_eur
        return total

    def cost_eur_dgt(self, sale_currency: str, sale_rate: Decimal | None) -> Decimal | None:
        """Suma de :meth:`ConsumedLot.cost_eur_dgt`; None si falta alguno."""
        total = Decimal("0")
        for lot in self.lots:
            cost = lot.cost_eur_dgt(sale_currency, sale_rate)
            if cost is None:
                return None
            total += cost
        return total


def simulate_fifo_sale(
    db: Session,
    *,
    tenant_id: int,
    company_id: int,
    quantity: Decimal,
    held_quantity: Decimal,
    sale_date: date | None = None,
) -> FifoSale | None:
    """Lotes FIFO que consumiría vender ``quantity`` hoy, o None sin lotes fiables.

    None cuando no hay compras individuales guardadas o cuando las compras y
    ventas guardadas no explican la posición actual (``held_quantity``): en
    ese caso el llamante usa el coste medio y lo dice.
    """
    sale_date = sale_date or date.today()
    rows = list(
        db.scalars(
            select(Transaction).where(
                Transaction.tenant_id == tenant_id,
                Transaction.company_id == company_id,
                Transaction.trade_date <= sale_date,
            )
        ).all()
    )
    legs = [
        row for row in rows
        if (row.action or "").lower() in BUY_ACTIONS | SELL_ACTIONS
        and row.quantity is not None and row.quantity > 0
    ]
    if not any((row.action or "").lower() in BUY_ACTIONS for row in legs):
        return None
    legs.sort(key=_fifo_sort_key)

    from app.services.portfolio_fx_service import PortfolioFXService

    fx_table = PortfolioFXService().fx_table(
        db,
        currencies={row.currency for row in legs if row.currency},
        base_currency=TAX_CURRENCY,
        as_of_max=sale_date,
    )
    def resolve_rate(currency, as_of):
        return _rate_not_older_than(
            fx_table, quote_currency=currency or TAX_CURRENCY,
            base_currency=TAX_CURRENCY, as_of=as_of, max_age_days=MAX_FX_AGE_DAYS,
        )

    lots, history = replay_tax_fifo(legs, resolve_rate, date.min, sale_date)
    if any(entry["over_sell"] for entry in history):
        return None
    if sum((lot["qty"] for lot in lots), Decimal("0")) != Decimal(held_quantity) or not 0 < quantity <= held_quantity:
        return None
    # Include deferred losses at their original euro value, not today's FX.
    for lot in lots:
        lot["unit_eur"] = (
            lot["unit_base"] + lot["deferred_base"] / lot["qty"]
            if lot["unit_base"] is not None and lot["deferred_base"] is not None else None
        )
        lot["unit"] += lot["deferred"] / lot["qty"]
    sale = consume_fifo(lots, quantity)
    apply_backward_repurchase(
        sale, lots,
        [(row.trade_date, row.quantity) for row in legs if row.action.lower() in BUY_ACTIONS],
        [(row.trade_date, row.quantity) for row in legs if row.action.lower() in SELL_ACTIONS],
        sale_date,
    )
    return sale


def apply_backward_repurchase(sale, lots, prior_buys, prior_sells, sale_date):
    """Share annual-report backward proportionality and initial-buy exception."""
    if any(lot["date"] is None for lot in lots):
        return  # callers must disclose that undated losses cannot be classified
    for lot in lots:
        lot.setdefault("capacity", lot["qty"])
    sale.blocking_qty = backward_repurchase_quantity(
        prior_buys, prior_sells, lots, sale_date, sale.quantity,
    )
    sale.blocking_dates = sorted({lot["date"] for lot in lots
                                 if lot["date"] >= sale_date - WASH_SALE_WINDOW
                                 and lot["qty"] > 0 and lot["capacity"] > 0}) if sale.blocking_qty else []


def consume_fifo(lots: deque[dict], quantity: Decimal) -> FifoSale:
    """Vende ``quantity`` de ``lots`` (ya en orden FIFO) y los deja con el resto.

    Cada lote es un dict con ``qty``, ``unit`` (coste unitario en su divisa),
    ``unit_eur`` (o None si falta el tipo), ``date`` y ``currency``. Es el
    mismo núcleo para la posición guardada y para una venta hipotética con
    los lotes que da el usuario en el chat.
    """
    sale = FifoSale(quantity=quantity)
    remaining = quantity
    while remaining > 0 and lots:
        lot = lots[0]
        take = min(lot["qty"], remaining)
        sale.lots.append(ConsumedLot(lot["date"], take, lot["unit_eur"], lot["unit"], lot["currency"]))
        lot["qty"] -= take
        remaining -= take
        if lot["qty"] == 0:
            lots.popleft()
    return sale


def repurchase_deadline(sale_date: date) -> date:
    """Último día en que una recompra bloquearía la pérdida de esta venta."""
    return sale_date + relativedelta(months=2)
