from collections.abc import Iterable

from app.valuation.dcf_fcff import DCFInputs, run_dcf


def _validate_base(base: DCFInputs) -> None:
    """Validación previa con mensajes fijos (sin filtrar internos)."""
    if base.shares_outstanding <= 0:
        raise ValueError("Sensitivity base inputs are invalid: shares must be positive")
    if base.revenue <= 0:
        raise ValueError("Sensitivity base inputs are invalid: revenue must be positive")
    if base.wacc <= base.terminal_growth:
        raise ValueError("Sensitivity base inputs are invalid: wacc must exceed terminal growth")


def sensitivity_grid(
    base: DCFInputs,
    growth_values: Iterable[float],
    wacc_values: Iterable[float],
) -> dict:
    """Grid crecimiento × WACC con aislamiento de fallo por celda.

    Ninguna celda rompe el grid: un fallo (p. ej. ``wacc <= g`` en esa
    celda) se devuelve como ``{"wacc": ..., "value_per_share": None,
    "error": ...}`` con mensaje fijo. La validación previa del ``base``
    (wacc>g, shares>0, revenue>0) sigue siendo dura: un base inválido
    lanza ``ValueError`` porque todo el grid sería ficticio.
    """
    _validate_base(base)
    rows = []
    for growth in growth_values:
        row = {"revenue_growth": growth, "values": []}
        for wacc in wacc_values:
            try:
                value = run_dcf(
                    DCFInputs(
                        revenue=base.revenue,
                        revenue_growth=growth,
                        fcf_margin=base.fcf_margin,
                        wacc=wacc,
                        terminal_growth=base.terminal_growth,
                        net_debt=base.net_debt,
                        shares_outstanding=base.shares_outstanding,
                        years=base.years,
                        minority_interest=base.minority_interest,
                        preferred_stock=base.preferred_stock,
                    )
                ).value_per_share
            except ValueError:
                row["values"].append(
                    {
                        "wacc": wacc,
                        "value_per_share": None,
                        "error": "cell_out_of_range",
                    }
                )
                continue
            row["values"].append({"wacc": wacc, "value_per_share": value})
        rows.append(row)
    return {"rows": rows, "trace": {"method": "dcf_sensitivity_grid"}}
