"""Escenarios con ingresos en caída: el bear nunca puede valer más que el base.

Bug: el suelo de crecimiento del bear (-5%) se aplicaba con ``max`` y, si el
base ya caía más de un 5% anual, el bear crecía MÁS que el base. Con márgenes
altos el valor bear superaba al base (p. ej. g=-15%, margen 50%, WACC 10%:
bear 34,64 > base 31,14 por acción), y la ficha mostraba un «pesimista» más
optimista que el caso base.

Los esperados se calculan a mano con la fórmula FCFF de 5 años + Gordon
(Damodaran, *Investment Valuation*, cap. 12), sin usar el motor:
    VP = sum_{t=1..5} R0 (1+g)^t m / (1+w)^t + R5 m (1+gT) / (w-gT) / (1+w)^5
R0=1000, 100 acciones, deuda neta 0, gT=2,5%.
  base: g=-15%, m=50%, w=10%  -> 31,1426 por acción
  bear: g=-15%, m=44%, w=12%  -> 22,3168 por acción (antes del arreglo: g=-5% -> 34,6364)
"""

import itertools

import pytest

from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.engines.sotp_engine import sotp_discount_sensitivity
from app.valuation.scenario_definitions import (
    holding_company_scenarios,
    mechanical_dcf_scenarios,
    speculative_causal_scenarios,
)


def _value(a: dict) -> float:
    return run_dcf(
        DCFInputs(1000.0, a["revenue_growth"], a["fcf_margin"], a["wacc"], a["terminal_growth"], 0.0, 100.0)
    ).value_per_share


def test_bear_de_empresa_en_caida_no_supera_al_base_valores_a_mano():
    bear, base, _ = mechanical_dcf_scenarios(-0.15, 0.50, 0.10, 0.025, 0.8)
    assert bear.assumptions["revenue_growth"] == pytest.approx(-0.15)
    assert _value(base.assumptions) == pytest.approx(31.142645937, rel=1e-9)
    assert _value(bear.assumptions) == pytest.approx(22.316831019, rel=1e-9)


@pytest.mark.parametrize(
    "growth,margin,wacc,terminal",
    list(
        itertools.product(
            [-0.15, -0.10, -0.06, -0.02, 0.05, 0.30], [0.05, 0.20, 0.50], [0.07, 0.10, 0.14], [0.0, 0.025]
        )
    ),
)
def test_drivers_y_valor_ordenados_bear_base_bull(growth, margin, wacc, terminal):
    bear, base, bull = mechanical_dcf_scenarios(growth, margin, wacc, terminal, 0.8)
    assert (
        bear.assumptions["revenue_growth"]
        <= base.assumptions["revenue_growth"]
        <= bull.assumptions["revenue_growth"]
    )
    assert bear.assumptions["wacc"] >= base.assumptions["wacc"]
    assert _value(bear.assumptions) <= _value(base.assumptions) <= _value(bull.assumptions)


@pytest.mark.parametrize(
    "growth,terminal",
    [(-0.15, 0.025), (-0.08, 0.02), (0.20, 0.005), (0.20, 0.0), (-0.10, -0.01)],
)
def test_especulativo_bear_no_sube_crecimiento_ni_terminal(growth, terminal):
    bear, base, _ = speculative_causal_scenarios(growth, 0.20, 0.12, terminal, 0.1, 0.5)
    assert bear.assumptions["revenue_growth"] <= base.assumptions["revenue_growth"]
    assert bear.assumptions["terminal_growth"] <= base.assumptions["terminal_growth"]


def test_holding_con_descuento_alto_el_bear_no_vale_mas_que_el_base():
    """NAV/acc 50, descuento base 50%: base = 50 x (1 - 0,50) = 25,00.
    Antes el tope del 45% estrechaba el bear a 45% -> 50 x 0,55 = 27,50 > base."""
    bear, base, _ = holding_company_scenarios(50.0, 0.50, 0.5)

    def value(s):
        return s.assumptions["nav_per_share"] * (1 - s.assumptions["holding_discount"])

    assert value(base) == pytest.approx(25.0)
    assert value(bear) == pytest.approx(25.0)
    assert value(bear) <= value(base)


def test_sensibilidad_sotp_fila_ancha_nunca_mas_estrecha_que_el_base():
    """NAV/acc 10, descuento base 65%: base = 3,50; la fila «ancha» no puede
    valer más (antes se recortaba a 60% -> 4,00)."""
    rows = {
        r["scenario"]: r for r in sotp_discount_sensitivity(nav_per_share=10.0, base_discount=0.65)["rows"]
    }
    assert rows["base_discount"]["value_per_share"] == pytest.approx(3.5)
    assert rows["wide_discount"]["value_per_share"] <= rows["base_discount"]["value_per_share"]
    assert rows["narrow_discount"]["value_per_share"] == pytest.approx(4.0)
