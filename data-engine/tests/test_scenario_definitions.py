"""Tests unitarios de `app.valuation.scenario_definitions`.

Sin BD, sin red: ponderacion por evidencia y escenarios causales/mecanicos.
"""

from __future__ import annotations

import math

import pytest

from app.valuation.scenario_definitions import (
    ScenarioDefinition,
    evidence_weighted_probabilities,
    holding_company_scenarios,
    mechanical_dcf_scenarios,
    speculative_causal_scenarios,
)

# ---------------- evidence_weighted_probabilities ----------------


def test_probabilidades_base_suman_uno():
    probs = evidence_weighted_probabilities(evidence_confidence=0.0)
    assert probs == pytest.approx({"bear": 0.30, "base": 0.40, "bull": 0.30})
    assert sum(probs.values()) == pytest.approx(1.0)


def test_confianza_alta_sube_el_escenario_base():
    probs = evidence_weighted_probabilities(evidence_confidence=1.0)
    assert probs["base"] == pytest.approx(0.64)
    assert probs["bull"] + probs["bear"] == pytest.approx(0.36)


def test_riesgo_de_financiacion_castiga_al_base():
    probs = evidence_weighted_probabilities(evidence_confidence=1.0, downside_risk=1.0)
    assert probs["base"] == pytest.approx(0.56)


def test_senal_positiva_inclina_el_reparto_hacia_bull():
    al_alza = evidence_weighted_probabilities(evidence_confidence=0.5, directional_signal=1.0)
    a_la_baja = evidence_weighted_probabilities(evidence_confidence=0.5, directional_signal=-1.0)
    assert al_alza["bull"] > al_alza["bear"]
    assert a_la_baja["bear"] > a_la_baja["bull"]


def test_entradas_fuera_de_rango_se_recortan():
    extremo = evidence_weighted_probabilities(
        evidence_confidence=99.0, directional_signal=-99.0, downside_risk=99.0
    )
    recortado = evidence_weighted_probabilities(
        evidence_confidence=1.0, directional_signal=-1.0, downside_risk=1.0
    )
    assert extremo == pytest.approx(recortado)


def test_base_nunca_baja_del_suelo_documentado():
    probs = evidence_weighted_probabilities(evidence_confidence=0.0, downside_risk=1.0)
    assert probs["base"] == pytest.approx(0.40)  # suelo 0.40


def test_reparto_del_tail_respeta_los_limites_de_upside():
    # upside_share clampado a [0.25, 0.75]: con signal -1 y risk 1 -> 0.25.
    probs = evidence_weighted_probabilities(
        evidence_confidence=0.0, directional_signal=-1.0, downside_risk=1.0
    )
    tail = 1.0 - probs["base"]
    assert probs["bull"] == pytest.approx(tail * 0.25)
    assert probs["bear"] == pytest.approx(tail * 0.75)


def test_nunca_probabilidades_negativas_en_todo_el_dominio():
    for confidence in (-1.0, 0.0, 0.5, 1.0, 2.0):
        for signal in (-2.0, -0.5, 0.0, 0.7, 3.0):
            for risk in (-1.0, 0.0, 0.5, 1.0, 5.0):
                probs = evidence_weighted_probabilities(
                    evidence_confidence=confidence,
                    directional_signal=signal,
                    downside_risk=risk,
                )
                assert sum(probs.values()) == pytest.approx(1.0)
                assert all(value >= 0.0 for value in probs.values())
                assert all(math.isfinite(value) for value in probs.values())
                assert 0.40 <= probs["base"] <= 0.68


# ---------------- mechanical_dcf_scenarios ----------------


def test_escenarios_mecanicos_orden_y_supuestos():
    scenarios = mechanical_dcf_scenarios(0.10, 0.20, 0.10, 0.02, 0.5)
    assert [s.name for s in scenarios] == ["bear", "base", "bull"]
    bear, base, bull = scenarios

    assert base.assumptions == {
        "revenue_growth": 0.10,
        "fcf_margin": 0.20,
        "wacc": 0.10,
        "terminal_growth": 0.02,
    }
    assert bear.assumptions["revenue_growth"] == pytest.approx(0.02)  # -8pp
    assert bear.assumptions["fcf_margin"] == pytest.approx(0.14)  # -6pp
    assert bear.assumptions["wacc"] == pytest.approx(0.12)  # +2pp
    assert bull.assumptions["revenue_growth"] == pytest.approx(0.18)  # +8pp
    assert bull.assumptions["fcf_margin"] == pytest.approx(0.26)  # +6pp
    assert bull.assumptions["wacc"] == pytest.approx(0.09)  # -1pp
    for scenario in scenarios:
        assert scenario.assumptions["terminal_growth"] == 0.02
        assert scenario.drivers
        assert scenario.description


def test_probabilidades_mecanicas_suman_uno():
    scenarios = mechanical_dcf_scenarios(0.10, 0.20, 0.10, 0.02, 0.5)
    assert sum(s.probability for s in scenarios) == pytest.approx(1.0)
    assert all(s.probability > 0 for s in scenarios)
    # direction = (0.10-0.10)*3 + (0.20-0.10)*2 = 0.20 -> sesgo alcista.
    assert [s.probability for s in scenarios] == pytest.approx(
        [0.2208, 0.52, 0.2592]
    )


def test_quema_de_caja_dispersa_solo_por_margen():
    # Con margen base negativo, variar crecimiento/WACC invertiría la
    # economía: crecer más quema más (bull peor) y descontar pérdidas a
    # más WACC las encoge (bear mejor). Solo el margen dispersa.
    bear, base, bull = mechanical_dcf_scenarios(0.10, -0.02, 0.10, 0.02, 0.0)
    assert bear.assumptions["fcf_margin"] == pytest.approx(-0.08)
    assert bear.assumptions["revenue_growth"] == base.assumptions["revenue_growth"]
    assert bear.assumptions["wacc"] == base.assumptions["wacc"]
    assert bull.assumptions["revenue_growth"] == base.assumptions["revenue_growth"]
    assert bull.assumptions["wacc"] == base.assumptions["wacc"]
    assert (
        bear.assumptions["fcf_margin"]
        < base.assumptions["fcf_margin"]
        < bull.assumptions["fcf_margin"]
    )
    assert base.assumptions["fcf_margin"] == pytest.approx(-0.02)


def test_techo_margen_bull():
    _, _, bull = mechanical_dcf_scenarios(0.10, 0.50, 0.10, 0.02, 0.0)
    assert bull.assumptions["fcf_margin"] == pytest.approx(0.45)


def test_wacc_bull_nunca_baja_del_crecimiento_terminal_mas_margen():
    _, _, bull = mechanical_dcf_scenarios(0.10, 0.20, 0.03, 0.025, 0.0)
    assert bull.assumptions["wacc"] == pytest.approx(0.035)
    assert bull.assumptions["wacc"] > 0.025


def test_crecimiento_muy_negativo_se_recorta_al_suelo():
    bear, _, _ = mechanical_dcf_scenarios(-0.30, 0.20, 0.10, 0.02, 0.0)
    assert bear.assumptions["revenue_growth"] == pytest.approx(-0.05)


# ---------------- speculative_causal_scenarios ----------------


def test_escenarios_especulativos_nombres_y_dilucion():
    scenarios = speculative_causal_scenarios(0.30, 0.0, 0.12, 0.02, 0.30, 0.2)
    assert [s.name for s in scenarios] == [
        "execution_delay_funding_stress",
        "base_commercialization",
        "accelerated_monetization",
    ]
    bear, base, bull = scenarios
    assert bear.assumptions["extra_dilution_pct"] == pytest.approx(0.30)
    assert base.assumptions["extra_dilution_pct"] == pytest.approx(0.30)
    assert bull.assumptions["extra_dilution_pct"] == pytest.approx(0.15)
    assert sum(s.probability for s in scenarios) == pytest.approx(1.0)


def test_margen_bear_especulativo_respeta_el_signo_y_el_orden():
    # Con margen base negativo (quema de caja), un suelo positivo en el bear
    # lo colocaba POR ENCIMA del base: bear mejor que base en valoracion.
    bear, base, bull = speculative_causal_scenarios(0.30, -0.15, 0.12, 0.02, 0.0, 0.0)
    assert bear.assumptions["fcf_margin"] == pytest.approx(-0.23)
    assert base.assumptions["fcf_margin"] == pytest.approx(-0.15)
    assert (
        bear.assumptions["fcf_margin"]
        < base.assumptions["fcf_margin"]
        < bull.assumptions["fcf_margin"]
    )


def test_margen_bear_mecanico_respeta_el_signo_y_el_orden():
    # El suelo de +0.5% del bear mecanico tenia el mismo defecto: con margen
    # base -15% el bear salia +0.5%, invertido sobre el base.
    bear, base, bull = mechanical_dcf_scenarios(0.05, -0.15, 0.10, 0.02, 0.0)
    assert bear.assumptions["fcf_margin"] == pytest.approx(-0.21)
    assert base.assumptions["fcf_margin"] == pytest.approx(-0.15)
    assert (
        bear.assumptions["fcf_margin"]
        < base.assumptions["fcf_margin"]
        < bull.assumptions["fcf_margin"]
    )


def test_dilucion_cero_mantiene_el_suelo_de_quince_por_ciento_en_bear():
    bear, base, bull = speculative_causal_scenarios(0.30, 0.05, 0.12, 0.02, 0.0, 0.0)
    assert bear.assumptions["extra_dilution_pct"] == pytest.approx(0.15)
    assert base.assumptions["extra_dilution_pct"] == 0.0
    assert bull.assumptions["extra_dilution_pct"] == 0.0


def test_dilucion_extrema_se_recorta_en_riesgo():
    scenarios = speculative_causal_scenarios(0.30, 0.05, 0.12, 0.02, 10.0, 0.0)
    assert all(math.isfinite(s.probability) for s in scenarios)
    assert sum(s.probability for s in scenarios) == pytest.approx(1.0)


def test_terminal_bear_especulativo_tiene_suelo():
    bear, _, bull = speculative_causal_scenarios(0.30, 0.05, 0.12, 0.001, 0.1, 0.0)
    assert bear.assumptions["terminal_growth"] == pytest.approx(0.01)
    assert bull.assumptions["wacc"] == pytest.approx(max(0.12 - 0.015, 0.001 + 0.015))


# ---------------- holding_company_scenarios ----------------


def test_escenarios_holding_descuentos_y_nav():
    scenarios = holding_company_scenarios(100.0, 0.20, 0.0)
    assert [s.name for s in scenarios] == ["bear", "base", "bull"]
    bear, base, bull = scenarios
    assert bear.assumptions["holding_discount"] == pytest.approx(0.35)  # +15pp
    assert base.assumptions == {
        "nav_per_share": 100.0,
        "holding_discount": 0.20,
    }
    assert bull.assumptions["nav_per_share"] == pytest.approx(112.0)  # +12%
    assert bull.assumptions["holding_discount"] == pytest.approx(0.12)  # -8pp
    assert sum(s.probability for s in scenarios) == pytest.approx(1.0)


def test_descuento_bear_con_techo_del_45_por_ciento():
    bear, _, _ = holding_company_scenarios(50.0, 0.50, 0.0)
    assert bear.assumptions["holding_discount"] == pytest.approx(0.45)


def test_descuento_bull_nunca_negativo():
    _, _, bull = holding_company_scenarios(50.0, 0.02, 0.0)
    assert bull.assumptions["holding_discount"] == 0.0


def test_descuento_cero_y_extremo_no_rompen():
    for discount in (0.0, 0.45, 1.0, -0.10):
        scenarios = holding_company_scenarios(10.0, discount, 1.0)
        assert all(isinstance(s, ScenarioDefinition) for s in scenarios)
        assert all(math.isfinite(s.probability) for s in scenarios)
        assert sum(s.probability for s in scenarios) == pytest.approx(1.0)


@pytest.mark.parametrize("margin", [0.45, 0.469359, 0.472190, 0.494225, 0.50])
def test_high_margin_bull_never_reduces_base_margin(margin):
    # Live SEC-derived FY2025 examples: PLTR .469359, ANET .472190,
    # MSCI .494225. The old .45 bull cap was below their base input.
    rows = {s.name: s for s in mechanical_dcf_scenarios(.08, margin, .10, .03, .8)}
    assert rows["bear"].assumptions["fcf_margin"] < margin
    assert rows["bull"].assumptions["fcf_margin"] >= rows["base"].assumptions["fcf_margin"]


def test_normal_margin_bull_cap_unchanged():
    rows = mechanical_dcf_scenarios(.08, .42, .10, .03, .8)
    assert rows[2].assumptions["fcf_margin"] == .45
