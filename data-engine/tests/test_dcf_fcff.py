"""Tests unitarios de calculo puro de `app.valuation.dcf_fcff`.

Sin BD, sin red, deterministas: solo aritmetica de descuento de flujos.
"""

from __future__ import annotations

import math

import pytest

from app.valuation.dcf_fcff import DCFInputs, DCFResult, TerminalFCFNotPositiveError, run_dcf


def _inputs(**overrides) -> DCFInputs:
    base = dict(
        revenue=100.0,
        revenue_growth=0.10,
        fcf_margin=0.20,
        wacc=0.10,
        terminal_growth=0.02,
        net_debt=50.0,
        shares_outstanding=10.0,
        years=2,
    )
    base.update(overrides)
    return DCFInputs(**base)


def test_caso_base_valores_conocidos():
    """Caso redondo verificado a mano (revenue 100, growth 10%, margin 20%)."""
    result = run_dcf(_inputs())

    assert isinstance(result, DCFResult)
    # Ano 1: revenue 110, fcf 22, df 1.1 -> pv 20. Ano 2: revenue 121, fcf 24.2, df 1.21 -> pv 20.
    assert result.forecast[0]["revenue"] == pytest.approx(110.0)
    assert result.forecast[0]["fcf"] == pytest.approx(22.0)
    assert result.forecast[0]["pv_fcf"] == pytest.approx(20.0)
    assert result.forecast[1]["pv_fcf"] == pytest.approx(20.0)
    assert result.trace["pv_explicit_fcf"] == pytest.approx(40.0)
    # terminal_fcf = 24.2 * 1.02 = 24.684; terminal_value = 24.684 / 0.08 = 308.55
    assert result.trace["terminal_fcf"] == pytest.approx(24.684)
    assert result.trace["terminal_value"] == pytest.approx(308.55)
    # pv_terminal = 308.55 / 1.21 = 255.0 -> EV 295, equity 245, 24.5/accion
    assert result.trace["pv_terminal_value"] == pytest.approx(255.0)
    assert result.enterprise_value == pytest.approx(295.0)
    assert result.equity_value == pytest.approx(245.0)
    assert result.value_per_share == pytest.approx(24.5)


def test_longitud_forecast_igual_a_years_y_trazable():
    result = run_dcf(_inputs(years=7))
    assert len(result.forecast) == 7
    assert [row["year"] for row in result.forecast] == list(range(1, 8))
    assert result.trace["method"] == "fcff_dcf"
    assert result.trace["inputs"]["years"] == 7
    # Cada fila del forecast es internamente coherente.
    for row in result.forecast:
        assert row["discount_factor"] == pytest.approx((1 + 0.10) ** row["year"])
        assert row["pv_fcf"] == pytest.approx(row["fcf"] / row["discount_factor"])
        assert row["fcf"] == pytest.approx(row["revenue"] * 0.20)


def test_years_minimo_acepta_uno():
    result = run_dcf(_inputs(years=1))
    assert len(result.forecast) == 1
    assert math.isfinite(result.enterprise_value)


def test_shares_no_positivas_lanza():
    with pytest.raises(ValueError, match="shares_outstanding must be positive"):
        run_dcf(_inputs(shares_outstanding=0.0))
    with pytest.raises(ValueError, match="shares_outstanding must be positive"):
        run_dcf(_inputs(shares_outstanding=-5.0))


def test_wacc_debe_superar_crecimiento_terminal():
    with pytest.raises(ValueError, match="wacc must be greater than terminal_growth"):
        run_dcf(_inputs(wacc=0.02, terminal_growth=0.02))
    with pytest.raises(ValueError, match="wacc must be greater than terminal_growth"):
        run_dcf(_inputs(wacc=0.01, terminal_growth=0.05))


def test_years_menor_que_uno_lanza():
    with pytest.raises(ValueError, match="years must be at least 1"):
        run_dcf(_inputs(years=0))
    with pytest.raises(ValueError, match="years must be at least 1"):
        run_dcf(_inputs(years=-3))


@pytest.mark.parametrize("overrides", [
    {"fcf_margin": -0.05}, {"fcf_margin": 0.0}, {"revenue": 0.0},
    {"terminal_growth": -1.0}, {"terminal_growth": -1.1},
])
def test_fcf_terminal_no_positivo_invalida_el_camino(overrides):
    with pytest.raises(TerminalFCFNotPositiveError, match="terminal fcf must be positive"):
        run_dcf(_inputs(**overrides))


def test_caja_neta_deuda_negativa_sube_el_valor_por_accion():
    apalancado = run_dcf(_inputs(net_debt=100.0))
    con_caja = run_dcf(_inputs(net_debt=-100.0))
    assert con_caja.equity_value == pytest.approx(apalancado.equity_value + 200.0)
    assert con_caja.value_per_share > apalancado.value_per_share


def test_crecimiento_extremo_sigue_finito():
    result = run_dcf(_inputs(revenue_growth=3.0, years=3))
    assert all(math.isfinite(row["pv_fcf"]) for row in result.forecast)
    assert math.isfinite(result.value_per_share)
    # Con semejante crecimiento el valor terminal domina.
    assert result.trace["pv_terminal_value"] > result.trace["pv_explicit_fcf"]


def test_wacc_casi_igual_a_terminal_infla_el_valor_pero_es_finito():
    result = run_dcf(_inputs(wacc=0.021, terminal_growth=0.02))
    assert result.trace["terminal_value"] > 0
    assert math.isfinite(result.trace["terminal_value"])
    assert math.isfinite(result.value_per_share)


def test_terminal_growth_negativo_aceptado():
    result = run_dcf(_inputs(terminal_growth=-0.03, wacc=0.08))
    assert result.trace["terminal_value"] == pytest.approx(
        result.forecast[-1]["fcf"] * 0.97 / 0.11
    )


def test_deuda_neta_mayor_que_enterprise_value_da_valor_por_accion_negativo():
    result = run_dcf(_inputs(net_debt=10_000.0, shares_outstanding=1000.0))
    assert result.equity_value < 0
    assert result.value_per_share < 0


def test_wacc_menor_que_menos_uno_se_rechaza_antes_del_descuento():
    with pytest.raises(ValueError, match="wacc must be greater than -1"):
        run_dcf(_inputs(wacc=-1.01, terminal_growth=-1.1))


@pytest.mark.parametrize("overrides,message", [
    ({"shares_outstanding": 0}, "shares_outstanding"),
    ({"wacc": 0.02}, "wacc must be greater than terminal_growth"),
    ({"years": 0}, "years must be at least 1"),
    ({"wacc": -1.01, "terminal_growth": -1.1}, "wacc must be greater than -1"),
    ({"terminal_growth": -1.0}, "terminal fcf must be positive"),
])
def test_validacion_convergencia_incluye_el_flujo_gordon(overrides, message):
    from app.valuation.dcf_fcff import ConvergenceDCFInputs, run_dcf_margin_convergence

    values = dict(revenue=100.0, revenue_growth=0.0, initial_fcf_margin=-0.2,
                  target_fcf_margin=0.2, wacc=0.1, terminal_growth=0.02,
                  net_debt=0.0, shares_outstanding=10.0, years=5)
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        run_dcf_margin_convergence(ConvergenceDCFInputs(**values))
