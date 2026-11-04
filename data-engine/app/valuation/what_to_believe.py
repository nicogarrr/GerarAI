"""«Qué hace falta creer»: lo que el precio de hoy exige al DCF ya calculado.

Solo LEE el resultado de la valoración (``ValuationService.value_company``):
reconstruye el DCF base desde su propia traza (``trace.scenarios.base.trace``:
ingresos, trayectoria de crecimiento y margen, tasas y puente EV -> equity) y
lo vuelve a descontar con la MISMA matemática (``run_path_dcf``). No cambia
cómo se calcula ningún valor publicado, ni el WACC, ni el crecimiento: el WACC
que se muestra como «usamos» es el que lleva la traza, con la política que
tenga el motor en cada momento (nunca se recalcula aquí).

Tres contrastes, todos generales (sin mapas de tickers):

1. WACC implícito: el WACC que iguala el DCF base al precio (bisección acotada
   en ``IMPLIED_WACC_BOUNDS``; fuera de esos límites, «fuera de rango» con el
   sentido). Lo mismo para el consenso de analistas cuando existe y está en la
   misma divisa.
2. Crecimiento implícito: se REUTILIZA el DCF inverso del motor
   (``reverse_dcf.required_revenue_growth``: crecimiento de la etapa 1 que
   justifica el precio con el WACC usado), no se duplica.
3. Valor terminal por múltiplo de salida: el mismo DCF con el terminal igual a
   ``EXIT_FCF_MULTIPLE`` veces el FCF del último año proyectado en vez de la
   perpetuidad de Gordon (contraste, no valor publicado), y el múltiplo de
   salida que haría falta para llegar al precio.

Motores que no son un DCF FCFF (bancos, aseguradoras, REIT, holdings,
pre-ingresos, escenarios...) o una valoración sin valor base -> «no aplica»
con el motivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel

from app.valuation.normalized_fcf import run_path_dcf

# Límites de la búsqueda del WACC implícito. Por debajo del 3 % un WACC no es
# coste de capital de una acción (es menos que un bono corporativo) y por
# encima del 25 % es capital riesgo: fuera de ahí se dice «fuera de rango».
IMPLIED_WACC_BOUNDS = (0.03, 0.25)
# Holgura mínima sobre el crecimiento terminal: con WACC <= g la perpetuidad
# no está definida (WaccNotAboveTerminalGrowthError en el motor).
IMPLIED_WACC_MIN_SPREAD = 0.0025
IMPLIED_WACC_ITERATIONS = 80
# Múltiplo de salida del contraste: 25 veces el FCF del último año proyectado
# (≈ 4 % de rentabilidad por FCF a la salida). Constante visible en la UI; es
# un contraste, no un supuesto del valor publicado.
EXIT_FCF_MULTIPLE = 25.0

# Métodos de la traza del escenario base que son un DCF FCFF reconstruible.
_DCF_METHODS = {"fcff_dcf", "fcff_dcf_multistage"}

WhatToBelieveStatus = Literal["ok", "not_applicable"]
SolveStatus = Literal["ok", "out_of_range", "not_available"]


@dataclass(frozen=True)
class DcfPaths:
    """El DCF base tal y como lo calculó el motor (unidades de su traza)."""

    revenue: float
    growth_path: tuple[float, ...]
    margin_path: tuple[float, ...]
    wacc: float
    terminal_growth: float
    net_debt: float
    shares_outstanding: float
    minority_interest: float = 0.0
    preferred_stock: float = 0.0


def _num(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


def _dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def dcf_paths_from_trace(base_trace: Any) -> DcfPaths | None:
    """Reconstruye el DCF base desde la traza de ``run_dcf``/``run_path_dcf``.

    None si la traza no es la de un DCF FCFF o le falta algún dato: nunca se
    rellena un hueco con un supuesto.
    """
    if not isinstance(base_trace, dict) or base_trace.get("method") not in _DCF_METHODS:
        return None
    inputs = base_trace.get("inputs")
    if not isinstance(inputs, dict):
        return None
    revenue = _num(inputs.get("revenue"))
    wacc = _num(inputs.get("wacc"))
    terminal = _num(inputs.get("terminal_growth"))
    net_debt = _num(inputs.get("net_debt"))
    shares = _num(inputs.get("shares_outstanding"))
    minority = _num(inputs.get("minority_interest") or 0.0)
    preferred = _num(inputs.get("preferred_stock") or 0.0)
    if None in (revenue, wacc, terminal, net_debt, shares, minority, preferred):
        return None
    if base_trace["method"] == "fcff_dcf_multistage":
        raw_growth = inputs.get("growth_path")
        raw_margin = inputs.get("margin_path")
        if not isinstance(raw_growth, list) or not isinstance(raw_margin, list):
            return None
        growth = [_num(v) for v in raw_growth]
        margin = [_num(v) for v in raw_margin]
    else:
        g = _num(inputs.get("revenue_growth"))
        m = _num(inputs.get("fcf_margin"))
        years = _num(inputs.get("years") or 5)
        if g is None or m is None or years is None or years < 1:
            return None
        growth = [g] * int(years)
        margin = [m] * int(years)
    if not growth or len(growth) != len(margin) or any(v is None for v in growth + margin):
        return None
    assert revenue is not None and wacc is not None and terminal is not None
    assert net_debt is not None and shares is not None
    if revenue <= 0 or shares <= 0:
        return None
    return DcfPaths(
        revenue=revenue,
        growth_path=tuple(float(v) for v in growth if v is not None),
        margin_path=tuple(float(v) for v in margin if v is not None),
        wacc=wacc,
        terminal_growth=terminal,
        net_debt=net_debt,
        shares_outstanding=shares,
        minority_interest=minority or 0.0,
        preferred_stock=preferred or 0.0,
    )


def value_at_wacc(paths: DcfPaths, wacc: float) -> float:
    """Valor por acción del DCF base con otro WACC (misma matemática)."""
    return run_path_dcf(
        revenue=paths.revenue,
        growth_path=list(paths.growth_path),
        margin_path=list(paths.margin_path),
        wacc=wacc,
        terminal_growth=paths.terminal_growth,
        net_debt=paths.net_debt,
        shares_outstanding=paths.shares_outstanding,
        minority_interest=paths.minority_interest,
        preferred_stock=paths.preferred_stock,
    ).value_per_share


def _explicit(paths: DcfPaths, wacc: float) -> tuple[float, float]:
    """(VP de los FCF explícitos, FCF del último año proyectado)."""
    revenue = paths.revenue
    present = 0.0
    fcf = 0.0
    for year, (growth, margin) in enumerate(zip(paths.growth_path, paths.margin_path), start=1):
        revenue *= 1 + growth
        fcf = revenue * margin
        present += fcf / (1 + wacc) ** year
    return present, fcf


def exit_multiple_value(paths: DcfPaths, wacc: float, multiple: float = EXIT_FCF_MULTIPLE) -> float:
    """El mismo DCF con terminal = ``multiple`` x FCF del último año."""
    present, last_fcf = _explicit(paths, wacc)
    years = len(paths.growth_path)
    enterprise = present + multiple * last_fcf / (1 + wacc) ** years
    equity = enterprise - paths.net_debt - paths.minority_interest - paths.preferred_stock
    return equity / paths.shares_outstanding


def implied_exit_multiple(paths: DcfPaths, wacc: float, target_value: float) -> float | None:
    """Múltiplo de salida (x FCF del último año) que iguala el DCF a ``target_value``.

    Lineal en el múltiplo; None si el último FCF no es positivo o el múltiplo
    resultante no lo es (el precio ya queda cubierto sin valor terminal).
    """
    present, last_fcf = _explicit(paths, wacc)
    if last_fcf <= 0:
        return None
    years = len(paths.growth_path)
    enterprise_needed = (
        target_value * paths.shares_outstanding
        + paths.net_debt
        + paths.minority_interest
        + paths.preferred_stock
    )
    multiple = (enterprise_needed - present) * (1 + wacc) ** years / last_fcf
    return multiple if multiple > 0 else None


def solve_implied_wacc(
    paths: DcfPaths,
    target_value: float,
    *,
    bounds: tuple[float, float] = IMPLIED_WACC_BOUNDS,
    iterations: int = IMPLIED_WACC_ITERATIONS,
) -> dict[str, Any]:
    """WACC que iguala el DCF base a ``target_value`` (bisección acotada).

    ``status``: ``ok`` con ``wacc``; ``out_of_range`` con ``direction``
    ``below_min`` (haría falta un WACC menor que el límite inferior: el precio
    está por encima de todo lo que el DCF da en el rango) o ``above_max``
    (haría falta más del límite superior); ``not_available`` si el DCF no es
    monótono en el rango (FCF negativos) o el objetivo no es positivo.
    """
    low = max(bounds[0], paths.terminal_growth + IMPLIED_WACC_MIN_SPREAD)
    high = bounds[1]
    base = {"bounds": [low, high], "target_value": target_value}
    if target_value <= 0 or low >= high:
        return {**base, "status": "not_available", "wacc": None, "direction": None}
    v_low = value_at_wacc(paths, low)
    v_high = value_at_wacc(paths, high)
    if not v_low > v_high:
        # Con FCF negativos el valor no baja al subir el WACC: no hay un
        # «WACC implícito» con sentido económico.
        return {**base, "status": "not_available", "wacc": None, "direction": None}
    if target_value > v_low:
        return {**base, "status": "out_of_range", "wacc": None, "direction": "below_min"}
    if target_value < v_high:
        return {**base, "status": "out_of_range", "wacc": None, "direction": "above_max"}
    lo, hi = low, high
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if value_at_wacc(paths, mid) > target_value:
            lo = mid
        else:
            hi = mid
    return {**base, "status": "ok", "wacc": (lo + hi) / 2, "direction": None}


class ImpliedWacc(BaseModel):
    status: SolveStatus
    target_price: float | None = None
    wacc: float | None = None
    # below_min: haría falta un WACC menor que bounds[0]; above_max: mayor que bounds[1].
    direction: Literal["below_min", "above_max"] | None = None
    bounds: list[float] = []


class ImpliedGrowth(BaseModel):
    """Crecimiento de la etapa 1 que justifica el precio (DCF inverso del motor)."""

    status: str
    required_revenue_growth: float | None = None
    current_revenue_growth: float | None = None
    method: str = "reverse_dcf_stage1_growth"


class ExitMultipleContrast(BaseModel):
    multiple: float = EXIT_FCF_MULTIPLE
    metric: Literal["terminal_year_fcf"] = "terminal_year_fcf"
    value_per_share: float | None = None
    gordon_value_per_share: float | None = None
    # Múltiplo de salida que igualaría el DCF al precio actual.
    implied_multiple_for_price: float | None = None


class WhatToBelieve(BaseModel):
    ticker: str
    status: WhatToBelieveStatus
    reason_code: (
        Literal["engine_not_dcf", "no_base_value", "no_price", "valuation_unavailable"] | None
    ) = None
    reason: str | None = None
    engine: str | None = None
    currency: str | None = None
    current_price: float | None = None
    base_value: float | None = None
    wacc_used: float | None = None
    terminal_growth: float | None = None
    implied_wacc_price: ImpliedWacc | None = None
    implied_wacc_consensus: ImpliedWacc | None = None
    consensus_price: float | None = None
    consensus_source: str | None = None
    implied_growth: ImpliedGrowth | None = None
    exit_multiple: ExitMultipleContrast | None = None


def _not_applicable(ticker: str, code: str, reason: str, engine: str | None) -> WhatToBelieve:
    return WhatToBelieve(
        ticker=ticker, status="not_applicable", reason_code=code,  # type: ignore[arg-type]
        reason=reason, engine=engine,
    )


def build_what_to_believe(
    ticker: str,
    valuation: dict[str, Any],
    *,
    consensus_price: float | None = None,
    consensus_currency: str | None = None,
    consensus_source: str | None = None,
) -> WhatToBelieve:
    """El bloque completo desde el resultado de ``value_company``.

    Las unidades: la traza del DCF va en la divisa de REPORTE y por acción
    ordinaria; el precio y el valor publicado van en la del LISTADO (y por
    ADR si hay ``adr_ratio``). La conversión es lineal, así que el factor se
    lee del propio resultado (valor base publicado / valor base de la traza)
    y sirve para cualquier divisa o ratio ADR sin volver a pedir tipos.
    """
    ticker = ticker.upper()
    trace = _dict(valuation.get("trace"))
    engine = trace.get("engine") if isinstance(trace.get("engine"), str) else None
    if valuation.get("status") not in ("ok", "partial"):
        return _not_applicable(
            ticker, "valuation_unavailable",
            "No hay una valoración DCF calculada para esta empresa.", engine,
        )
    base_entry = _dict(_dict(trace.get("scenarios")).get("base"))
    paths = dcf_paths_from_trace(base_entry.get("trace"))
    if paths is None:
        return _not_applicable(
            ticker, "engine_not_dcf",
            "El método de valoración de esta empresa no es un DCF de flujos de caja libres.",
            engine,
        )
    ratio = _num(valuation.get("adr_ratio")) or 1.0
    published_base = _num(valuation.get("base_value"))
    trace_base = value_at_wacc(paths, paths.wacc)
    if published_base is None or published_base <= 0 or trace_base <= 0:
        return _not_applicable(
            ticker, "no_base_value",
            "El DCF base no da un valor positivo por acción.", engine,
        )
    # Unidades de la traza -> unidades del precio cotizado.
    to_price_units = published_base * ratio / trace_base
    price = _num(valuation.get("current_price"))
    currency = valuation.get("value_currency") if isinstance(valuation.get("value_currency"), str) else None
    if price is None or price <= 0:
        return _not_applicable(
            ticker, "no_price",
            "Sin precio de mercado no se puede decir qué exige el precio.", engine,
        )

    def implied(target: float) -> ImpliedWacc:
        solved = solve_implied_wacc(paths, target / to_price_units)
        return ImpliedWacc(
            status=solved["status"], target_price=target, wacc=solved["wacc"],
            direction=solved["direction"], bounds=solved["bounds"],
        )

    consensus_ok = (
        consensus_price is not None
        and consensus_price > 0
        and currency is not None
        and (consensus_currency or "").upper() == currency.upper()
    )
    reverse = _dict(valuation.get("reverse_dcf"))
    required = _num(reverse.get("required_revenue_growth")) if reverse.get("status") == "ok" else None
    wacc_used = _num(trace.get("wacc"))
    if wacc_used is None:
        wacc_used = paths.wacc
    exit_value = exit_multiple_value(paths, paths.wacc) * to_price_units
    return WhatToBelieve(
        ticker=ticker,
        status="ok",
        engine=engine,
        currency=currency,
        current_price=price,
        base_value=published_base * ratio,
        wacc_used=wacc_used,
        terminal_growth=paths.terminal_growth,
        implied_wacc_price=implied(price),
        implied_wacc_consensus=implied(float(consensus_price)) if consensus_ok and consensus_price else None,
        consensus_price=consensus_price if consensus_ok else None,
        consensus_source=consensus_source if consensus_ok else None,
        implied_growth=ImpliedGrowth(
            status=str(reverse.get("status") or "not_available"),
            required_revenue_growth=required,
            current_revenue_growth=paths.growth_path[0],
        ),
        exit_multiple=ExitMultipleContrast(
            value_per_share=exit_value if exit_value > 0 else None,
            gordon_value_per_share=published_base * ratio,
            implied_multiple_for_price=implied_exit_multiple(paths, paths.wacc, price / to_price_units),
        ),
    )
