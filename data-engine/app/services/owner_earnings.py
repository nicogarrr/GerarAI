"""Beneficio del propietario («owner earnings»), definición única del repo.

Fuente: Warren E. Buffett, carta a los accionistas de Berkshire Hathaway de
1986 (apéndice sobre la compra de Scott Fetzer). El «owner earnings» es:

    (a) el beneficio declarado
  + (b) depreciación, agotamiento, amortización y otros cargos sin caja
  - (c) el capex medio anual que el negocio necesita para mantener su
        posición competitiva y su volumen de unidades
  - el capital circulante adicional que haga falta para lo mismo.

Convención de signos (la del estado de flujos de caja):

* ``capital_expenditure`` se guarda NEGATIVO (salida de caja: FMP
  ``capitalExpenditure`` < 0 y la ingesta SEC/ESEF niega ``PaymentsToAcquire…``).
  Aquí se usa siempre su valor absoluto, así un capex nunca se suma dos veces
  aunque llegue con signo cambiado.
* ``change_in_working_capital`` sigue el signo del flujo de caja: NEGATIVO
  cuando el circulante ABSORBE caja (sube) y POSITIVO cuando la LIBERA
  (baja). Es el signo de FMP ``changeInWorkingCapital``; el concepto SEC
  ``IncreaseDecreaseInOperatingCapital`` llega con el signo contrario y la
  ingesta lo niega antes de guardarlo. Por eso se SUMA:

    OE = beneficio neto + D&A + ΔCC(flujo de caja) − |capex de mantenimiento|

Ejemplo: 100 + 30 + (−10) − |−40| = 80.

Capex de mantenimiento: los emisores no lo publican separado. Si existe el
hecho ``maintenance_capex`` se usa; si no, se ESTIMA con la regla declarada que
ya usaban las métricas calculadas del repo: min(|capex|, D&A) (el capex por
encima de la amortización se trata como crecimiento). La traza dice cuál de
los dos se usó.

Un input ausente nunca se toma como 0: la función devuelve ``None`` y quien la
llama nombra el input que falta.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

OWNER_EARNINGS_FORMULA = (
    "net_income + depreciation_amortization + change_in_working_capital "
    "- abs(maintenance_capex); change_in_working_capital in cash-flow sign "
    "(negative = working capital absorbed cash); maintenance_capex reported, "
    "or estimated as min(abs(capital_expenditure), depreciation_amortization) "
    "when not separately reported (Buffett, Berkshire Hathaway 1986 letter)"
)

MAINTENANCE_RULE_REPORTED = "reported maintenance_capex"
MAINTENANCE_RULE_ESTIMATED = (
    "min(abs(capital_expenditure), depreciation_amortization); maintenance capex "
    "is not separately reported - declared conservative estimate"
)

WORKING_CAPITAL_SIGN_CONVENTION = (
    "cash-flow sign: negative = working capital absorbed cash, positive = released"
)


@dataclass(frozen=True)
class OwnerEarnings:
    value: Decimal
    maintenance_capex: Decimal
    maintenance_capex_rule: str
    estimated_growth_capex: Decimal | None


def maintenance_capex_estimate(
    capital_expenditure: Decimal, depreciation_amortization: Decimal
) -> Decimal:
    """Capex de mantenimiento estimado: min(|capex|, D&A), nunca negativo."""
    return min(abs(capital_expenditure), max(depreciation_amortization, Decimal("0")))


def owner_earnings(
    *,
    net_income: Decimal,
    depreciation_amortization: Decimal,
    change_in_working_capital: Decimal,
    capital_expenditure: Decimal | None = None,
    maintenance_capex: Decimal | None = None,
) -> OwnerEarnings | None:
    """OE de Buffett (1986) con ΔCC en signo de flujo de caja.

    Devuelve ``None`` si no hay ni ``maintenance_capex`` ni
    ``capital_expenditure`` para estimarlo.
    """
    if maintenance_capex is not None:
        maintenance = abs(maintenance_capex)
        rule = MAINTENANCE_RULE_REPORTED
        growth = (
            max(Decimal("0"), abs(capital_expenditure) - maintenance)
            if capital_expenditure is not None
            else None
        )
    elif capital_expenditure is not None:
        maintenance = maintenance_capex_estimate(capital_expenditure, depreciation_amortization)
        rule = MAINTENANCE_RULE_ESTIMATED
        growth = abs(capital_expenditure) - maintenance
    else:
        return None
    value = net_income + depreciation_amortization + change_in_working_capital - maintenance
    return OwnerEarnings(
        value=value,
        maintenance_capex=maintenance,
        maintenance_capex_rule=rule,
        estimated_growth_capex=growth,
    )
