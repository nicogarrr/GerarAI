"""r5-valor: plazo del DCF inverso que la tabla de tasas base no mide → N/D CON motivo.

Antes: el DCF inverso guarda ``horizon_years`` 6, 8 o 9 y la tabla mide 1, 2, 3, 5, 7 y 10 años;
``for_annual_revenue`` devolvía None y el check quedaba None, sin decir por qué (aviso de r5-bugs).
Ahora: ``{"share": None, "reason": "la tasa base mide plazos de 1, 2, 3, 5, 7 y 10 años y el DCF
inverso usa 6: …"}``. No se interpola entre 5 y 7 años (no es una cifra medida).
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.estimate_base_rates import table_horizons
from app.services.financial_health import HealthFact
from app.services.valuation_summary import _reverse_base_rate_check

FACTS = [HealthFact(1, "revenue", 2022, 8e8, "USD", date(2022, 12, 31), "u", "sec"),
         HealthFact(2, "revenue", 2025, 1e9, "USD", date(2025, 12, 31), "u", "sec")]


def test_shipped_table_horizons() -> None:
    assert table_horizons() == (1, 2, 3, 5, 7, 10)
    assert table_horizons({"groups": {"h4|*|*|*": {}, "h12|x|y|z": {}, "otra": {}}}) == (4, 12)


@pytest.mark.parametrize("horizon", [4, 6, 8, 9])
def test_unmeasured_horizon_is_nd_with_reason(horizon: int) -> None:
    out = _reverse_base_rate_check(SimpleNamespace(cik=None), FACTS,  # type: ignore[arg-type]
                                   {"status": "ok", "trace": {"horizon_years": horizon}}, 0.10)
    assert out is not None and out["share"] is None and out["horizon_years"] == horizon
    assert out["reason"] == (f"la tasa base mide plazos de 1, 2, 3, 5, 7 y 10 años y el DCF inverso usa "
                             f"{horizon}: no se compara un plazo distinto")


@pytest.mark.parametrize("horizon", [1, 5, 10])
def test_measured_horizon_still_gets_the_share(horizon: int) -> None:
    out = _reverse_base_rate_check(SimpleNamespace(cik=None), FACTS,  # type: ignore[arg-type]
                                   {"status": "ok", "trace": {"horizon_years": horizon}}, 0.10)
    assert out is not None and isinstance(out["share"], float) and out["horizon_years"] == horizon
