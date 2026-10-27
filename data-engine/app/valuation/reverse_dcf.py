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
