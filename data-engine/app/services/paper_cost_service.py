"""Supuestos de coste del track record simulado (comision + spread).

NADA de esto es un dato de mercado: son supuestos explicitos, configurables y
versionados. El set vigente se persiste en cada trade al ejecutarlo
(`cost_assumption_version`), de modo que cambiar el supuesto no reescribe la
historia. Los trades anteriores a este modelo no tienen costes: su neto es N/D,
nunca se retro-rellena.

Comision: cantidad fija EN LA DIVISA DEL TRADE por ejecucion (entrada y salida
por separado). Spread: bps sobre el nocional de cada ejecucion. Son
simplificaciones declaradas, no la tarifa de ningun broker.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.config import Settings, get_settings
from app.models.paper_trading import PaperTrade

LABEL = "supuesto"
_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class PaperCostAssumptions:
    commission_flat: Decimal  # por ejecucion, en la divisa del trade
    spread_bps: Decimal  # puntos basicos sobre el nocional, por ejecucion
    version: str


def assumptions_from_settings(settings: Settings) -> PaperCostAssumptions:
    commission = settings.paper_trade_commission_flat
    spread = settings.paper_trade_spread_bps
    return PaperCostAssumptions(
        commission_flat=commission,
        spread_bps=spread,
        version=f"supuesto-v1|fija={commission}|spread_bps={spread}",
    )


def current_assumptions() -> PaperCostAssumptions:
    return assumptions_from_settings(get_settings())


def execution_fee(price: Decimal, quantity: Decimal, assumptions: PaperCostAssumptions) -> Decimal:
    """Comision fija + spread_bps del nocional, por UNA ejecucion."""
    notional = price * quantity
    fee = assumptions.commission_flat + notional * assumptions.spread_bps / Decimal(10000)
    return fee.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def pnl_net(
    row: PaperTrade,
    price: Decimal | None,
    assumptions: PaperCostAssumptions | None = None,
) -> Decimal | None:
    """P&L neto del supuesto persistido. None si no hay bruto o el trade es legado.

    En posiciones abiertas la salida aun no existe: se descuenta la comision de
    entrada real y una salida ESTIMADA al precio dado con el supuesto vigente.
    """
    if row.entry_price is None or price is None or row.entry_fee is None:
        return None
    sign = Decimal(1) if row.direction == "long" else Decimal(-1)
    gross = (price - row.entry_price) * row.quantity * sign
    if row.status == "closed":
        if row.exit_fee is None:
            return None  # cierre anterior al modelo de costes
        exit_fee = row.exit_fee
    else:
        current = assumptions or current_assumptions()
        exit_fee = execution_fee(price, row.quantity, current)
    # Dividendos devengados (DividendRecord con fuente); NULL = aun no computado
    # en un trade nuevo o no computable en uno legado (cuyo neto ya es N/D por fees).
    dividends = row.dividends_total if row.dividends_total is not None else Decimal(0)
    return gross - row.entry_fee - exit_fee + dividends
