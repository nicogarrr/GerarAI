"""Tests de propiedades (invariantes) de las fórmulas de valoración.

Casos aleatorios con semilla fija (``random.Random``), 200 por propiedad: son
deterministas y no necesitan dependencias nuevas. Cada propiedad cita la
identidad estándar que comprueba.
"""

from __future__ import annotations

import math
import random

import pytest

from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.dilution_model import DilutionInput, run_dilution
from app.valuation.dividend_equity import (
    DdmInputError,
    DdmInputs,
    fcfe_bridge,
    gordon_value,
    run_ddm,
)
from app.valuation.engines.sector_specific import _pb_sensitivity_rows
from app.valuation.reverse_dcf import ReverseDCFInputs, solve_required_growth
from app.valuation.scenario_model import Scenario, probability_weighted_value
from app.valuation.sensitivity import sensitivity_grid
from app.valuation.sotp import run_sotp

N_CASOS = 200


def _casos(semilla: int, n: int = N_CASOS) -> list[random.Random]:
    base = random.Random(semilla)
    return [random.Random(base.random()) for _ in range(n)]


def _dcf_aleatorio(rng: random.Random) -> DCFInputs:
    wacc = rng.uniform(0.06, 0.15)
    return DCFInputs(
        revenue=rng.uniform(10, 10_000),
        revenue_growth=rng.uniform(-0.10, 0.40),
        fcf_margin=rng.uniform(0.01, 0.40),
        wacc=wacc,
        terminal_growth=rng.uniform(-0.01, wacc - 0.01),
        net_debt=rng.uniform(-500, 500),
        shares_outstanding=rng.uniform(1, 1_000),
        years=rng.randint(1, 10),
    )


def _con(inputs: DCFInputs, **cambios: float) -> DCFInputs:
    datos = dict(inputs.__dict__)
    datos.update(cambios)
    return DCFInputs(**datos)


@pytest.mark.parametrize("rng", _casos(101), ids=lambda _: "")
def test_dcf_crece_con_g_terminal_y_cae_con_el_wacc(rng):
    """Gordon: VT = FCF·(1 + g)/(r − g) crece con g (si g < r) y cae con r
    para FCF > 0 (Damodaran, *Investment Valuation*, cap. 12)."""
    base = _dcf_aleatorio(rng)
    g_alto = base.terminal_growth + (base.wacc - base.terminal_growth) * 0.5
    assert run_dcf(_con(base, terminal_growth=g_alto)).enterprise_value > run_dcf(base).enterprise_value
    assert run_dcf(_con(base, wacc=base.wacc + 0.01)).enterprise_value < run_dcf(base).enterprise_value


@pytest.mark.parametrize("rng", _casos(102), ids=lambda _: "")
def test_dcf_rechaza_g_mayor_o_igual_que_wacc(rng):
    """Con g ≥ r la perpetuidad de Gordon no es finita: el DCF debe negarse."""
    base = _dcf_aleatorio(rng)
    with pytest.raises(ValueError):
        run_dcf(_con(base, terminal_growth=base.wacc + rng.uniform(0, 0.05)))


@pytest.mark.parametrize("rng", _casos(103), ids=lambda _: "")
def test_dcf_puente_y_por_accion(rng):
    """equity = EV − deuda neta y valor/acción = equity/acciones; el EV es la
    suma de los VP explícitos más el VP del valor terminal."""
    inputs = _dcf_aleatorio(rng)
    out = run_dcf(inputs)
    assert out.enterprise_value == pytest.approx(out.trace["pv_explicit_fcf"] + out.trace["pv_terminal_value"])
    assert out.equity_value == pytest.approx(out.enterprise_value - inputs.net_debt)
    assert out.value_per_share == pytest.approx(out.equity_value / inputs.shares_outstanding)
    # El valor por acción es lineal en 1/acciones: duplicar acciones lo divide entre 2.
    doble = run_dcf(_con(inputs, shares_outstanding=inputs.shares_outstanding * 2))
    assert doble.value_per_share == pytest.approx(out.value_per_share / 2)


@pytest.mark.parametrize("rng", _casos(104), ids=lambda _: "")
def test_reverse_dcf_invierte_el_dcf(rng):
    """Si el precio es el valor del DCF con crecimiento g, el reverse DCF
    devuelve g (Mauboussin & Rappaport, *Expectations Investing*)."""
    base = _dcf_aleatorio(rng)
    g = rng.uniform(-0.20, 0.70)
    precio = run_dcf(_con(base, revenue_growth=g, net_debt=-abs(base.net_debt))).value_per_share
    out = solve_required_growth(
        ReverseDCFInputs(
            market_price=precio,
            revenue=base.revenue,
            fcf_margin=base.fcf_margin,
            wacc=base.wacc,
            terminal_growth=base.terminal_growth,
            net_debt=-abs(base.net_debt),
            shares_outstanding=base.shares_outstanding,
            years=base.years,
        )
    )
    assert out["out_of_bounds"] is False
    assert out["required_revenue_growth"] == pytest.approx(g, abs=1e-6)


@pytest.mark.parametrize("rng", _casos(105), ids=lambda _: "")
def test_gordon_monotono_y_rechaza_g_mayor_o_igual_que_ke(rng):
    """P = D0·(1 + g)/(ke − g): crece con g, cae con ke; con g ≥ ke no hay
    precio finito (CFA L2, Discounted Dividend Valuation)."""
    ke = rng.uniform(0.05, 0.15)
    g = rng.uniform(-0.03, ke - 0.01)
    d0 = rng.uniform(0.1, 10)
    p = gordon_value(d0, ke, g)
    assert p > 0
    assert gordon_value(d0, ke, g + (ke - g) / 2) > p
    assert gordon_value(d0, ke + 0.01, g) < p
    with pytest.raises(DdmInputError):
        gordon_value(d0, ke, ke + rng.uniform(0, 0.05))


@pytest.mark.parametrize("rng", _casos(106), ids=lambda _: "")
def test_ddm_multietapa_con_g_constante_es_gordon(rng):
    """Si g1 = g2 (dentro de los límites), el DDM de N etapas es el Gordon de
    una etapa: Σ D0(1+g)^t/(1+ke)^t + VT/(1+ke)^N = D0(1+g)/(ke − g)."""
    ke = rng.uniform(0.07, 0.14)
    g = rng.uniform(-0.04, 0.05)
    d0 = rng.uniform(0.1, 10)
    out = run_ddm(
        DdmInputs(
            dividend_per_share=d0,
            cost_of_equity=ke,
            stage1_growth=g,
            stage1_years=rng.randint(0, 15),
            stage2_growth=g,
            shares_diluted=1.0,
        )
    )
    assert out.value_per_share == pytest.approx(gordon_value(d0, ke, g), rel=1e-9)


@pytest.mark.parametrize("rng", _casos(107), ids=lambda _: "")
def test_fcfe_es_lineal_en_cada_termino(rng):
    """FCFE = NI − (capex − D&A) + Δdeuda − ΔWC (CFA L2): cada unidad de capex
    resta una, cada unidad de deuda nueva suma una; la retención no cambia
    el FCFE de un ejercicio."""
    kwargs = {
        "net_income": rng.uniform(-100, 500),
        "capex": rng.uniform(0, 300),
        "depreciation_amortization": rng.uniform(0, 200),
        "retention_ratio": rng.uniform(0, 1),
        "delta_total_debt": rng.uniform(-100, 100),
        "delta_working_capital": rng.uniform(-50, 50),
    }
    base = fcfe_bridge(**kwargs)["fcfe"]
    assert fcfe_bridge(**{**kwargs, "capex": kwargs["capex"] + 1})["fcfe"] == pytest.approx(base - 1)
    assert fcfe_bridge(**{**kwargs, "delta_total_debt": kwargs["delta_total_debt"] + 1})["fcfe"] == pytest.approx(base + 1)
    assert fcfe_bridge(**{**kwargs, "retention_ratio": rng.uniform(0, 1)})["fcfe"] == pytest.approx(base)


@pytest.mark.parametrize("rng", _casos(108), ids=lambda _: "")
def test_dilucion_conserva_el_valor(rng):
    """Equity post = equity pre + capital captado; emitir al valor por acción
    es neutro, por debajo diluye y por encima es acretivo (CFA L2 Equity)."""
    acciones = rng.uniform(1, 1_000)
    valor = rng.uniform(1, 200)
    capital = rng.uniform(0, 10_000)
    neutra = run_dilution(DilutionInput(acciones, capital, valor, valor))
    assert neutra["post_equity_value"] == pytest.approx(valor * acciones + capital)
    assert neutra["diluted_value_per_share"] == pytest.approx(valor)
    assert neutra["diluted_value_per_share"] * neutra["pro_forma_shares"] == pytest.approx(neutra["post_equity_value"])
    if capital > 0:
        barata = run_dilution(DilutionInput(acciones, capital, valor * rng.uniform(0.2, 0.95), valor))
        cara = run_dilution(DilutionInput(acciones, capital, valor * rng.uniform(1.05, 3), valor))
        assert barata["diluted_value_per_share"] < valor < cara["diluted_value_per_share"]


@pytest.mark.parametrize("rng", _casos(109), ids=lambda _: "")
def test_escenarios_invariantes_a_la_escala_de_probabilidades(rng):
    """E[V] = Σ (p_i/Σp)·V_i: multiplicar todas las p por k no cambia nada y
    E[V] queda entre el mínimo y el máximo de los escenarios."""
    escenarios = [Scenario(f"s{i}", rng.uniform(0.01, 5), rng.uniform(-50, 500)) for i in range(rng.randint(1, 6))]
    k = rng.uniform(0.1, 100)
    ev = probability_weighted_value(escenarios)["expected_value"]
    escalado = probability_weighted_value([Scenario(s.name, s.probability * k, s.value_per_share) for s in escenarios])
    assert escalado["expected_value"] == pytest.approx(ev)
    valores = [s.value_per_share for s in escenarios]
    assert min(valores) - 1e-9 <= ev <= max(valores) + 1e-9


@pytest.mark.parametrize("rng", _casos(110), ids=lambda _: "")
def test_suma_de_partes_es_aditiva(rng):
    """EV de la suma de partes = Σ métrica·múltiplo; añadir un segmento suma
    exactamente su valor."""
    segmentos = [{"metric": rng.uniform(1, 500), "multiple": rng.uniform(1, 30)} for _ in range(rng.randint(1, 5))]
    deuda = rng.uniform(-200, 800)
    acciones = rng.uniform(1, 100)
    out = run_sotp(segmentos, deuda, acciones)
    assert out["enterprise_value"] == pytest.approx(sum(s["metric"] * s["multiple"] for s in segmentos))
    extra = {"metric": rng.uniform(1, 100), "multiple": rng.uniform(1, 20)}
    out2 = run_sotp([*segmentos, extra], deuda, acciones)
    assert out2["equity_value"] - out["equity_value"] == pytest.approx(extra["metric"] * extra["multiple"])


@pytest.mark.parametrize("rng", _casos(111), ids=lambda _: "")
def test_rejilla_de_sensibilidad_es_el_dcf_celda_a_celda(rng):
    """Cada celda de la rejilla es run_dcf con ese (g, WACC); con WACC ≤ g
    terminal la celda es N/D, nunca un número."""
    base = _dcf_aleatorio(rng)
    g = rng.uniform(-0.05, 0.30)
    waccs = [base.terminal_growth - 0.01, base.terminal_growth, base.wacc, base.wacc + 0.02]
    celdas = sensitivity_grid(base, [g], waccs)["rows"][0]["values"]
    assert celdas[0]["value_per_share"] is None
    assert celdas[1]["value_per_share"] is None
    for celda, wacc in zip(celdas[2:], waccs[2:], strict=True):
        esperado = run_dcf(_con(base, revenue_growth=g, wacc=wacc)).value_per_share
        assert celda["value_per_share"] == pytest.approx(esperado)


@pytest.mark.parametrize("rng", _casos(113), ids=lambda _: "")
def test_pb_justificado_acotado(rng):
    """El P/B justificado (ROE − g)/(ke − g) se acota a [0,25; 3] y el valor
    por acción es libro·P/B·factor (CFA L2, Market-Based Valuation)."""
    ke = rng.uniform(0.06, 0.15)
    g = rng.uniform(0, ke - 0.006)
    book = rng.uniform(1, 200)
    factor = rng.uniform(0.75, 1.25)
    for fila in _pb_sensitivity_rows(
        book_per_share=book, roe=rng.uniform(-0.2, 0.6), cost_of_equity=ke, growth=g, underwriting_factor=factor
    )["rows"]:
        assert 0.25 <= fila["justified_pb"] <= 3.0
        assert fila["value_per_share"] == pytest.approx(book * fila["justified_pb"] * factor)
        assert math.isfinite(fila["value_per_share"])
