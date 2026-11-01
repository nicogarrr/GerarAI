from dataclasses import dataclass

from app.valuation.dcf_fcff import DCFInputs, run_dcf


@dataclass(frozen=True)
class ReverseDCFInputs:
    market_price: float
    revenue: float
    fcf_margin: float
    wacc: float
    terminal_growth: float
    net_debt: float
    shares_outstanding: float
    low_growth: float = -0.25
    high_growth: float = 0.75
    years: int = 5
    minority_interest: float = 0.0
    preferred_stock: float = 0.0


def _validate_inputs(inputs: ReverseDCFInputs) -> None:
    """Validación previa con mensajes fijos (sin filtrar internos)."""
    if inputs.market_price <= 0:
        raise ValueError("Reverse DCF inputs are invalid: market price must be positive")
    if inputs.revenue <= 0:
        raise ValueError("Reverse DCF inputs are invalid: revenue must be positive")
    if inputs.shares_outstanding <= 0:
        raise ValueError("Reverse DCF inputs are invalid: shares must be positive")
    if inputs.wacc <= inputs.terminal_growth:
        raise ValueError("Reverse DCF inputs are invalid: wacc must exceed terminal growth")
    if inputs.low_growth >= inputs.high_growth:
        raise ValueError("Reverse DCF inputs are invalid: growth bounds are inverted")


def _value_at(inputs: ReverseDCFInputs, growth: float) -> float:
    return run_dcf(
        DCFInputs(
            revenue=inputs.revenue,
            revenue_growth=growth,
            fcf_margin=inputs.fcf_margin,
            wacc=inputs.wacc,
            terminal_growth=inputs.terminal_growth,
            net_debt=inputs.net_debt,
            shares_outstanding=inputs.shares_outstanding,
            years=inputs.years,
            minority_interest=inputs.minority_interest,
            preferred_stock=inputs.preferred_stock,
        )
    ).value_per_share


def solve_required_growth(inputs: ReverseDCFInputs, iterations: int = 60) -> dict:
    """Crecimiento requerido por bisección, con flag ``out_of_bounds``.

    Si el precio de mercado queda fuera del rango valorable
    ``[value(low), value(high)]``, el crecimiento requerido caería fuera de
    los bounds: se devuelve igualmente el resultado pero con
    ``out_of_bounds=True`` para que ningún consumidor lo lea como un
    crecimiento alcanzable.
    """
    _validate_inputs(inputs)
    if inputs.fcf_margin <= 0:
        # With non-positive FCF margin the model value does not rise with
        # growth (more revenue means more burn), so a "required growth" is not
        # a meaningful quantity. Withhold it instead of returning a bisection
        # artefact with status ok.
        return {
            "required_revenue_growth": None,
            "market_price": inputs.market_price,
            "solved_value_per_share": None,
            "out_of_bounds": True,
            "status": "not_applicable",
            "reason": "fcf_margin is not positive; reverse DCF on revenue growth is undefined",
            "trace": {
                "method": "binary_search_reverse_dcf",
                "iterations": 0,
                "growth_bounds": [inputs.low_growth, inputs.high_growth],
                "fcf_margin": inputs.fcf_margin,
                "out_of_bounds": True,
            },
        }
    low = inputs.low_growth
    high = inputs.high_growth

    low_value = _value_at(inputs, low)
    high_value = _value_at(inputs, high)
    floor, ceiling = (low_value, high_value) if low_value <= high_value else (high_value, low_value)
    out_of_bounds = inputs.market_price < floor or inputs.market_price > ceiling
    increasing = low_value <= high_value

    for _ in range(iterations):
        mid = (low + high) / 2
        value = _value_at(inputs, mid)

        if (value < inputs.market_price) == increasing:
            low = mid
        else:
            high = mid

    required_growth = (low + high) / 2
    result_value = _value_at(inputs, required_growth)

    if out_of_bounds:
        # Outside the valueable growth range the bisection saturates at a
        # bound, so ``required_growth`` is an artefact of the search grid and
        # not a growth rate the model can produce. Returning the saturated
        # number made consumers publish "the price requires -25% revenue
        # growth" when the truth is "the price is outside every valueable
        # scenario", so the value is withheld and only the bounds are reported.
        return {
            "required_revenue_growth": None,
            "market_price": inputs.market_price,
            "solved_value_per_share": result_value,
            "out_of_bounds": True,
            "status": "out_of_bounds",
            "reason": (
                f"market_price {inputs.market_price} is outside the valueable range "
                f"[{floor}, {ceiling}] for growth in "
                f"[{inputs.low_growth}, {inputs.high_growth}]; no required growth exists"
            ),
            "trace": {
                "method": "binary_search_reverse_dcf",
                "iterations": iterations,
                "growth_bounds": [inputs.low_growth, inputs.high_growth],
                "bound_values": [low_value, high_value],
                "saturated_growth": required_growth,
                "out_of_bounds": True,
            },
        }

    return {
        "required_revenue_growth": required_growth,
        "market_price": inputs.market_price,
        "solved_value_per_share": result_value,
        "out_of_bounds": False,
        "status": "ok",
        "trace": {
            "method": "binary_search_reverse_dcf",
            "iterations": iterations,
            "growth_bounds": [inputs.low_growth, inputs.high_growth],
            "bound_values": [low_value, high_value],
            "out_of_bounds": False,
        },
    }


def value_split(
    *,
    revenue: float,
    growth: float,
    fcf_margin: float,
    wacc: float,
    terminal_growth: float,
    years: int,
) -> dict[str, float] | None:
    """Reparto del valor descontado: años 1–5, 6–10 y 11 en adelante (valor terminal).

    Misma convención que ``run_dcf`` (FCF = ingresos × margen, descuento al WACC a final
    de año): los años del horizonte crecen a ``growth`` y, si el horizonte es menor de 10,
    los años restantes hasta el 10 crecen ya al crecimiento terminal (es la misma
    perpetuidad, solo desplegada), así que los tres trozos suman el valor del modelo.
    """
    if revenue <= 0 or fcf_margin <= 0 or wacc <= terminal_growth:
        return None
    last = max(10, years)
    buckets = {"years_1_5": 0.0, "years_6_10": 0.0, "years_11_plus": 0.0}
    current = revenue
    fcf = 0.0
    for year in range(1, last + 1):
        current *= 1 + (growth if year <= years else terminal_growth)
        fcf = current * fcf_margin
        key = "years_1_5" if year <= 5 else "years_6_10" if year <= 10 else "years_11_plus"
        buckets[key] += fcf / (1 + wacc) ** year
    buckets["years_11_plus"] += fcf * (1 + terminal_growth) / (wacc - terminal_growth) / (1 + wacc) ** last
    total = sum(buckets.values())
    if total <= 0:
        return None
    return {key: round(value / total, 4) for key, value in buckets.items()}


def implied_perpetual_growth(*, fcf: float, enterprise_value: float, wacc: float) -> float | None:
    """Crecimiento perpetuo que descuenta el precio: g = WACC − FCF / EV (None si EV ≤ 0)."""
    if enterprise_value <= 0:
        return None
    return round(wacc - fcf / enterprise_value, 4)


def growth_sensitivity(inputs: ReverseDCFInputs, *, wacc_step: float = 0.01, margin_step: float = 0.02) -> dict:
    """Crecimiento exigido con WACC ±1 punto y margen FCF ±2 puntos (rejilla 3×3)."""
    waccs = [round(inputs.wacc + d, 4) for d in (-wacc_step, 0.0, wacc_step)]
    margins = [round(inputs.fcf_margin + d, 4) for d in (-margin_step, 0.0, margin_step)]
    rows = []
    for wacc in waccs:
        row: list[float | None] = []
        for margin in margins:
            if wacc <= inputs.terminal_growth or margin <= 0:
                row.append(None)
                continue
            solved = solve_required_growth(
                ReverseDCFInputs(**{**inputs.__dict__, "wacc": wacc, "fcf_margin": margin})
            )
            value = solved.get("required_revenue_growth")
            row.append(round(value, 4) if value is not None else None)
        rows.append(row)
    return {"wacc": waccs, "fcf_margin": margins, "required_growth": rows}
