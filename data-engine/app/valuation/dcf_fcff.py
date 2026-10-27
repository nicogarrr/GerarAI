from dataclasses import dataclass


@dataclass(frozen=True)
class DCFInputs:
    revenue: float
    revenue_growth: float
    fcf_margin: float
    wacc: float
    terminal_growth: float
    net_debt: float
    shares_outstanding: float
    years: int = 5
    # Otros derechos sobre el EV que no son del accionista común (puente
    # completo EV -> equity: Damodaran, *Investment Valuation*, cap. 16; CFA
    # Level II, "Free Cash Flow Valuation"). Valor contable reportado; 0 si el
    # emisor no los declara (lo habitual cuando no existen).
    minority_interest: float = 0.0
    preferred_stock: float = 0.0


@dataclass(frozen=True)
class DCFResult:
    enterprise_value: float
    equity_value: float
    value_per_share: float
    forecast: list[dict]
    trace: dict


def run_dcf(inputs: DCFInputs) -> DCFResult:
    if inputs.shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive")
    if inputs.wacc <= inputs.terminal_growth:
        raise ValueError("wacc must be greater than terminal_growth")
    if inputs.years < 1:
        raise ValueError("years must be at least 1")
    if 1 + inputs.wacc <= 0:
        # (1 + wacc) ** year alternaria de signo con un WACC <= -1: los
        # factores de descuento darian negativos y el valor presente, inventado.
        raise ValueError("wacc must be greater than -1")

    forecast = []
    present_value = 0.0
    revenue = inputs.revenue

    for year in range(1, inputs.years + 1):
        revenue *= 1 + inputs.revenue_growth
        fcf = revenue * inputs.fcf_margin
        discount_factor = (1 + inputs.wacc) ** year
        pv_fcf = fcf / discount_factor
        present_value += pv_fcf
        forecast.append(
            {
                "year": year,
                "revenue": revenue,
                "fcf": fcf,
                "discount_factor": discount_factor,
                "pv_fcf": pv_fcf,
            }
        )

    terminal_fcf = forecast[-1]["fcf"] * (1 + inputs.terminal_growth)
    terminal_value = terminal_fcf / (inputs.wacc - inputs.terminal_growth)
    pv_terminal_value = terminal_value / ((1 + inputs.wacc) ** inputs.years)
    enterprise_value = present_value + pv_terminal_value
    equity_value = (
        enterprise_value - inputs.net_debt - inputs.minority_interest - inputs.preferred_stock
    )
    value_per_share = equity_value / inputs.shares_outstanding

    # El valor terminal se lleva la mayor parte del EV en casi cualquier DCF de
    # 5 años, y su peso crece sin límite al acercarse el WACC al g. Con un
    # spread de 1 pp, el mismo modelo da 96x más de valor. Se expone el peso
    # y el spread para que quien lee el resultado vea de cuanto depende.
    terminal_share = (
        pv_terminal_value / enterprise_value if enterprise_value > 0 else None
    )
    spread = inputs.wacc - inputs.terminal_growth

    return DCFResult(
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=value_per_share,
        forecast=forecast,
        trace={
            "method": "fcff_dcf",
            "inputs": inputs.__dict__,
            "terminal_fcf": terminal_fcf,
            "terminal_value": terminal_value,
            "pv_terminal_value": pv_terminal_value,
            "pv_explicit_fcf": present_value,
            "wacc_minus_growth": spread,
            "pv_terminal_share_of_ev": terminal_share,
            "equity_bridge": {
                "enterprise_value": enterprise_value,
                "net_debt": inputs.net_debt,
                "minority_interest": inputs.minority_interest,
                "preferred_stock": inputs.preferred_stock,
                "equity_value": equity_value,
            },
        },
    )

