"""C2: contrato de cada puerta de los evals de valoracion.

Dos cosas se comprueban aqui, y las dos se han-equivocado antes en este repo:

1. Una puerta que devuelve ``passed=True`` cuando su clave no esta es una puerta
   que se puede silenciar omitiendo la clave. ``NON_SKIPPABLE_GATES`` nombra las
   que no lo admiten y estos tests construyen el caso minimo donde falta la clave.
2. Una puerta que nunca falla no es una puerta. Cada puerta del registro se
   prueba con un artefacto correcto y con uno que no lo es; sin lo segundo, "999
   checks en verde" no dice nada.

Los artefactos son a mano, minimos y con el contrato COMPLETO de ``value()``: si
un artefacto de test no cumple el contrato, ``gate_does_not_omit_itself`` falla y
el fallo se atribuye al fixture equivocado y no a la puerta que se queria probar.
"""

from __future__ import annotations

import math

import pytest

from evals.valuation.valuation_gates import (
    GATES,
    NON_SKIPPABLE_GATES,
    RESULT_CONTRACT_KEYS,
    VALUE_KEYS,
    _scenario_band,
    gate_adr_ratio_basis,
    gate_bear_le_base_le_bull,
    gate_does_not_omit_itself,
    gate_engine_publishable_status,
    gate_expected_value_within_band,
    gate_missing_inputs_declared,
    gate_no_sign_flip_on_negative_fcf,
    gate_no_silent_zero_net_debt,
    gate_probabilities_sum_to_one,
    gate_routing_expected,
    gate_sensitivity_covers_base,
    gate_trace_records_evidence,
    gate_value_matches_closed_form,
)

FINITE = {10.0, 15.0, 20.0}


def _artifact(**overrides) -> dict:
    """A published valuation with a complete contract and sane numbers."""
    artifact = {
        "ticker": "EV",
        "model_type": "eval",
        "status": "ok",
        "publishable": True,
        "current_price": 12.0,
        "bear_value": 10.0,
        "base_value": 15.0,
        "bull_value": 20.0,
        "expected_value": 15.0,
        "margin_of_safety": 0.25,
        "missing_inputs": [],
        "reverse_dcf": {},
        "publication_blockers": [],
        "adr_ratio": None,
        "value_per_share_basis": "ordinary_share",
        "comparable_price_basis": "listed_share",
        "listed_share_values": None,
        "sensitivity": {
            "rows": [
                {"scenario": "low", "value_per_share": 10.0},
                {"scenario": "base", "value_per_share": 15.0},
                {"scenario": "high", "value_per_share": 20.0},
            ]
        },
        "moat": {},
        "trace": {
            "engine": "standard_dcf",
            "model_version": "valuation-engines-v2",
            "probabilities": {"bear": 0.2, "base": 0.6, "bull": 0.2},
            "fact_ids": {"revenue": 1, "shares_diluted": 2},
            "periods": {"revenue": "FY2025", "shares_diluted": "FY2025"},
            "comparable_price": 12.0,
        },
    }
    artifact.update(overrides)
    return artifact


def _case(artifact=None, expected=None, *, engine="standard_dcf", facts=None) -> dict:
    artifact = _artifact() if artifact is None else artifact
    base_expected = {
        "engine_key": engine,
        "status": artifact.get("status", "ok"),
        "publishable": artifact.get("publishable", True),
        "missing_inputs": artifact.get("missing_inputs", []),
        "publication_blockers": artifact.get("publication_blockers", []),
        "closed_form": {key: artifact.get(key) for key in VALUE_KEYS},
        "adr_ratio": artifact.get("adr_ratio"),
    }
    base_expected.update(expected or {})
    trace = artifact.get("trace") or {}
    artifact["_routing"] = {
        "resolved_engine": engine,
        "trace_engine": trace.get("engine", engine),
    }
    return {
        "id": "unit",
        "engine": engine,
        "artifact": artifact,
        "expected": base_expected,
        "facts": {"revenue": 1000, "net_debt": 100} if facts is None else facts,
    }


def _refusal(**overrides) -> dict:
    artifact = _artifact(
        status="insufficient_data",
        publishable=False,
        bear_value=None,
        base_value=None,
        bull_value=None,
        expected_value=None,
        margin_of_safety=None,
        missing_inputs=["revenue"],
        sensitivity={"rows": []},
        trace={
            "engine": "standard_dcf",
            "model_version": "valuation-engines-v2",
            "input_source": "insufficient_data",
        },
    )
    artifact.update(overrides)
    return artifact


# --------------------------------------------------------------------------
# contrato del resultado
# --------------------------------------------------------------------------


def test_result_contract_is_what_the_omission_gate_defends():
    assert set(RESULT_CONTRACT_KEYS) >= set(VALUE_KEYS)
    assert "trace" in RESULT_CONTRACT_KEYS
    assert "missing_inputs" in RESULT_CONTRACT_KEYS


def test_complete_result_passes_the_contract_gate():
    assert gate_does_not_omit_itself(_case())["passed"] is True


@pytest.mark.parametrize("key", RESULT_CONTRACT_KEYS)
def test_contract_gate_fails_when_a_contract_key_is_absent(key):
    artifact = _artifact()
    del artifact[key]
    result = gate_does_not_omit_itself(_case(artifact))
    assert result["passed"] is False
    assert key in result["details"][0]
    assert "no puede omitirse" in result["details"][0]


def test_contract_gate_fails_when_trace_is_not_a_dict():
    assert gate_does_not_omit_itself(_case(_artifact(trace=[])))["passed"] is False


# --------------------------------------------------------------------------
# gates no omitibles: la clave que falta es un fallo, no un "no aplica"
# --------------------------------------------------------------------------


def _case_with_key_removed(gate_name: str) -> dict:
    case = _case()
    if gate_name == "gate_does_not_omit_itself":
        del case["artifact"]["sensitivity"]
    elif gate_name in {"probabilities_sum_to_one", "expected_value_within_band"}:
        del case["artifact"]["trace"]["probabilities"]
    else:
        del case["expected"][gate_name.replace("missing_inputs_declared", "missing_inputs")
                               .replace("value_matches_closed_form", "closed_form")
                               .replace("routing_expected", "engine_key")
                               .replace("engine_publishable_status", "status")]
    return case


@pytest.mark.parametrize("gate_name", NON_SKIPPABLE_GATES)
def test_non_skippable_gate_fails_when_its_key_is_missing(gate_name):
    """Cada puerta de ``NON_SKIPPABLE_GATES`` muerde con la clave ausente."""
    gate = GATES[gate_name]
    broken = _case_with_key_removed(gate_name)
    result = gate(broken)
    assert result["passed"] is False, gate_name
    assert "el gate no puede omitirse" in " ".join(result["details"]), gate_name


def test_every_registered_gate_returns_the_three_key_contract():
    for name, gate in GATES.items():
        result = gate(_case())
        assert set(result) == {"gate", "passed", "details"}, name
        assert result["gate"] == name
        assert isinstance(result["passed"], bool), name
        assert isinstance(result["details"], list), name


def test_non_skippable_tuple_only_names_registered_gates():
    assert set(NON_SKIPPABLE_GATES) <= set(GATES)


# --------------------------------------------------------------------------
# estado publicado
# --------------------------------------------------------------------------


def test_publishable_status_passes_on_a_clean_result():
    assert gate_engine_publishable_status(_case())["passed"] is True


def test_declared_status_must_match_the_artifact():
    result = gate_engine_publishable_status(_case(expected={"status": "partial"}))
    assert result["passed"] is False


def test_blockers_forbid_publishable_true():
    artifact = _artifact(publication_blockers=["traceable_wacc"])
    result = gate_engine_publishable_status(
        _case(artifact, {"publication_blockers": ["traceable_wacc"], "publishable": True})
    )
    assert result["passed"] is False


def test_a_publishable_result_may_not_carry_blockers():
    result = gate_engine_publishable_status(
        _case(_artifact(publication_blockers=["x"]), {"publication_blockers": ["x"]})
    )
    assert result["passed"] is False


def test_a_refusal_may_not_publish_a_value():
    result = gate_engine_publishable_status(_case(_refusal(base_value=12.0)))
    assert result["passed"] is False


def test_a_refusal_is_never_publishable():
    result = gate_engine_publishable_status(
        _case(_refusal(), {"publishable": True})
    )
    assert result["passed"] is False


def test_unknown_status_is_rejected():
    assert gate_engine_publishable_status(
        _case(_artifact(status="draft"), {"status": "draft"})
    )["passed"] is False


# --------------------------------------------------------------------------
# banda de escenarios
# --------------------------------------------------------------------------


def test_band_passes_when_ordered():
    assert gate_bear_le_base_le_bull(_case())["passed"] is True


def test_band_fails_when_the_order_is_inverted():
    result = gate_bear_le_base_le_bull(_case(_artifact(bear_value=18.0, base_value=15.0)))
    assert result["passed"] is False


def test_band_fails_on_a_missing_leg():
    result = gate_bear_le_base_le_bull(_case(_artifact(bull_value=None)))
    assert result["passed"] is False


def test_expected_value_must_sit_inside_the_band():
    outside = gate_expected_value_within_band(_case(_artifact(expected_value=25.0)))
    assert outside["passed"] is False
    inside = gate_expected_value_within_band(
        _case(_artifact(base_value=16.0, expected_value=15.6))
    )
    assert inside["passed"] is True


def test_expected_value_must_equal_the_probability_weighted_mean():
    artifact = _artifact(expected_value=16.0, trace={
        **_artifact()["trace"],
        "probabilities": {"bear": 0.2, "base": 0.6, "bull": 0.2},
    })
    result = gate_expected_value_within_band(_case(artifact))
    assert result["passed"] is False
    # 0.2*10 + 0.6*15 + 0.2*20 == 15.0
    artifact["expected_value"] = 15.0
    assert gate_expected_value_within_band(_case(artifact))["passed"] is True


def test_scenario_probabilities_are_accepted_when_flat_probabilities_are_absent():
    """El DCF y el SOTP solo publican ``trace.scenarios[*].definition.probability``."""
    trace = {
        "engine": "standard_dcf",
        "model_version": "valuation-engines-v2",
        "scenarios": {
            "bear": {"definition": {"probability": 0.25}, "value_per_share": 10.0},
            "base": {"definition": {"probability": 0.5}, "value_per_share": 15.0},
            "bull": {"definition": {"probability": 0.25}, "value_per_share": 20.0},
        },
    }
    band = _scenario_band(_artifact(), trace)
    assert band is not None
    assert abs(sum(band[0].values()) - 1.0) < 1e-12
    assert gate_expected_value_within_band(_case(_artifact(trace=trace)))["passed"] is True


# --------------------------------------------------------------------------
# forma cerrada
# --------------------------------------------------------------------------


def test_closed_form_matches():
    assert gate_value_matches_closed_form(_case())["passed"] is True


def test_closed_form_fails_on_a_wrong_number():
    """Un numero del motor que se aparta de la forma cerrada tiene que FALLAR."""
    result = gate_value_matches_closed_form(
        _case(expected={"closed_form": {"base_value": 15.5}})
    )
    assert result["passed"] is False
    assert "base_value" in result["details"][0]


def test_closed_form_fails_on_a_value_that_should_be_null():
    result = gate_value_matches_closed_form(
        _case(_artifact(status="ok", publishable=False), expected={
            "status": "ok", "publishable": False,
            "closed_form": {"base_value": None},
        })
    )
    assert result["passed"] is False


def test_closed_form_allows_a_null_the_artifact_also_keeps_null():
    artifact = _artifact(status="partial", publishable=False,
                         base_value=None, expected_value=None)
    case = _case(artifact, {"status": "partial", "publishable": False})
    assert gate_value_matches_closed_form(case)["passed"] is True


def test_closed_form_tolerance_is_relative_not_absolute():
    artifact = _artifact(base_value=1_000_000.0, expected_value=1_000_000.0)
    case = _case(artifact, {"closed_form": {"base_value": 1_000_000.5}})
    assert gate_value_matches_closed_form(case)["passed"] is True


def test_closed_form_rejects_an_unknown_key():
    result = gate_value_matches_closed_form(
        _case(expected={"closed_form": {"enterprise_value": 5.0}})
    )
    assert result["passed"] is False


# --------------------------------------------------------------------------
# probabilidades
# --------------------------------------------------------------------------


def test_probabilities_must_sum_to_one():
    assert gate_probabilities_sum_to_one(_case())["passed"] is True


@pytest.mark.parametrize("total", [0.9, 1.1])
def test_probabilities_that_do_not_sum_to_one_fail(total):
    trace = {**_artifact()["trace"],
             "probabilities": {"bear": total / 3, "base": total / 3, "bull": total / 3}}
    assert gate_probabilities_sum_to_one(_case(_artifact(trace=trace)))["passed"] is False


def test_negative_probability_fails():
    trace = {**_artifact()["trace"],
             "probabilities": {"bear": -0.1, "base": 0.8, "bull": 0.3}}
    assert gate_probabilities_sum_to_one(_case(_artifact(trace=trace)))["passed"] is False


def test_two_scenarios_are_not_three():
    trace = {**_artifact()["trace"], "probabilities": {"bear": 0.5, "bull": 0.5}}
    assert gate_probabilities_sum_to_one(_case(_artifact(trace=trace)))["passed"] is False


# --------------------------------------------------------------------------
# sensibilidad
# --------------------------------------------------------------------------


def test_sensitivity_needs_three_distinct_values():
    artifact = _artifact(sensitivity={"rows": [
        {"value_per_share": 10.0}, {"value_per_share": 15.0}, {"value_per_share": 15.0},
    ]})
    assert gate_sensitivity_covers_base(_case(artifact))["passed"] is False


def test_sensitivity_needs_to_contain_the_base():
    artifact = _artifact(sensitivity={"rows": [
        {"value_per_share": 30.0}, {"value_per_share": 40.0}, {"value_per_share": 50.0},
    ]})
    assert gate_sensitivity_covers_base(_case(artifact))["passed"] is False


def test_sensitivity_reads_the_dcf_grid_cells():
    artifact = _artifact(sensitivity={"rows": [
        {"revenue_growth": 0.04, "values": [
            {"wacc": 0.08, "value_per_share": 10.0},
            {"wacc": 0.09, "value_per_share": 15.0},
            {"wacc": 0.10, "value_per_share": 20.0},
        ]},
    ]})
    assert gate_sensitivity_covers_base(_case(artifact))["passed"] is True


def test_sensitivity_fails_on_an_empty_table():
    assert gate_sensitivity_covers_base(_case(_artifact(sensitivity={"rows": []})))["passed"] is False


def test_sensitivity_fails_on_a_non_finite_cell():
    artifact = _artifact(sensitivity={"rows": [
        {"value_per_share": 10.0}, {"value_per_share": math.inf}, {"value_per_share": 20.0},
    ]})
    assert gate_sensitivity_covers_base(_case(artifact))["passed"] is False


# --------------------------------------------------------------------------
# missing_inputs
# --------------------------------------------------------------------------


def test_missing_inputs_must_match_the_declaration():
    assert gate_missing_inputs_declared(_case())["passed"] is True
    assert gate_missing_inputs_declared(
        _case(_artifact(missing_inputs=["shares_diluted"]))
    )["passed"] is True
    # El artefacto dice una cosa y el caso declara otra: la puerta tiene que morder.
    assert gate_missing_inputs_declared(
        _case(_artifact(missing_inputs=["shares_diluted"]), {"missing_inputs": []})
    )["passed"] is False


def test_missing_inputs_ignores_order_but_not_content():
    assert gate_missing_inputs_declared(
        _case(_refusal(), {"missing_inputs": ["revenue"]})
    )["passed"] is True
    assert gate_missing_inputs_declared(
        _case(_artifact(missing_inputs=["a", "b"]), {"missing_inputs": ["b", "c"]})
    )["passed"] is False


# --------------------------------------------------------------------------
# deuda neta silenciosa
# --------------------------------------------------------------------------


def test_declared_net_debt_passes():
    assert gate_no_silent_zero_net_debt(_case(facts={"net_debt": 100}))["passed"] is True


def test_refusal_without_net_debt_passes():
    assert gate_no_silent_zero_net_debt(_case(_refusal(), facts={"revenue": 1}))["passed"] is True


def test_publishable_value_without_net_debt_fails():
    """La puente EV - net_debt con 0 inventado es justo lo que esta puerta caza."""
    result = gate_no_silent_zero_net_debt(_case(facts={"revenue": 1}))
    assert result["passed"] is False
    assert "supuesto 0 en silencio" in result["details"][0]


def test_a_declared_source_of_zero_on_a_non_final_result_is_accepted():
    artifact = _artifact(publishable=False, trace={
        **_artifact()["trace"],
        "net_debt_source": "missing_assumed_zero",
    })
    assert gate_no_silent_zero_net_debt(_case(artifact, {"publishable": False}, facts={"revenue": 1}))["passed"] is True


def test_a_declared_source_of_zero_on_a_published_result_fails():
    artifact = _artifact(trace={**_artifact()["trace"], "net_debt_source": "missing_assumed_zero"})
    assert gate_no_silent_zero_net_debt(_case(artifact, facts={"revenue": 1}))["passed"] is False


def test_engines_without_an_equity_bridge_are_out_of_scope():
    """bank/insurer valoran el capital: no hay puente que pueda mentir."""
    for engine in ("bank", "insurer"):
        result = gate_no_silent_zero_net_debt(_case(engine=engine, facts={"roe": 0.1}))
        assert result["passed"] is True
        assert "no construye puente" in result["details"][0]


# --------------------------------------------------------------------------
# salto de signo con FCF negativo
# --------------------------------------------------------------------------


def test_standard_dcf_refuses_a_reported_cash_burn():
    case = _case(
        _refusal(missing_inputs=["non_negative_fcf_margin"]),
        {"status": "insufficient_data", "publishable": False,
         "missing_inputs": ["non_negative_fcf_margin"]},
        facts={"revenue": 1000, "free_cash_flow": -80},
    )
    assert gate_no_sign_flip_on_negative_fcf(case)["passed"] is True


def test_standard_dcf_publishing_a_burn_fails():
    case = _case(facts={"revenue": 1000, "free_cash_flow": -80})
    assert gate_no_sign_flip_on_negative_fcf(case)["passed"] is False


def test_standard_dcf_publishing_a_burn_with_the_wrong_reason_fails():
    case = _case(
        _refusal(missing_inputs=["shares_diluted"]),
        {"status": "insufficient_data", "publishable": False,
         "missing_inputs": ["shares_diluted"]},
        facts={"revenue": 1000, "free_cash_flow": -80},
    )
    assert gate_no_sign_flip_on_negative_fcf(case)["passed"] is False


def test_pre_revenue_keeps_the_sign_of_the_burn():
    trace = {
        "engine": "pre_revenue",
        "model_version": "valuation-engines-v2",
        "scenarios": {
            "execution_delay_funding_stress": {
                "definition": {"probability": 0.3},
                "value_per_share": -8.0,
                "undiluted_value_per_share": -8.0,
            },
            "base_commercialization": {
                "definition": {"probability": 0.5},
                "value_per_share": -4.0,
                "undiluted_value_per_share": -4.0,
            },
        },
    }
    artifact = _artifact(
        status="ok",
        bear_value=-8.0,
        base_value=-4.0,
        bull_value=-2.0,
        expected_value=-4.6,
        trace=trace,
    )
    case = _case(
        artifact,
        {"engine_key": "pre_revenue", "expected_value": -4.6},
        engine="pre_revenue",
        facts={"revenue": 100, "fcf_margin": -0.6, "net_debt": 200},
    )
    assert gate_no_sign_flip_on_negative_fcf(case)["passed"] is True


def test_pre_revenue_diluting_a_burn_towards_zero_fails():
    trace = {
        "engine": "pre_revenue",
        "model_version": "valuation-engines-v2",
        "scenarios": {
            "base_commercialization": {
                "definition": {"probability": 0.5},
                "value_per_share": -1.2,
                "undiluted_value_per_share": -4.0,
            },
        },
    }
    case = _case(
        _artifact(trace=trace, bear_value=-8.0, base_value=-1.2, bull_value=-2.0,
                  expected_value=-4.6),
        {"engine_key": "pre_revenue", "expected_value": -4.6},
        engine="pre_revenue",
        facts={"revenue": 100, "fcf_margin": -0.6, "net_debt": 200},
    )
    result = gate_no_sign_flip_on_negative_fcf(case)
    assert result["passed"] is False
    assert "dilucion" in result["details"][0]


def test_a_positive_base_on_a_burn_with_net_debt_fails():
    case = _case(
        _artifact(base_value=3.0),
        engine="pre_revenue",
        facts={"revenue": 100, "fcf_margin": -0.6, "net_debt": 200},
    )
    assert gate_no_sign_flip_on_negative_fcf(case)["passed"] is False


def test_the_gate_refuses_to_run_on_a_case_that_is_not_a_burn():
    result = gate_no_sign_flip_on_negative_fcf(
        _case(facts={"revenue": 1000, "free_cash_flow": 120})
    )
    assert result["passed"] is False
    assert "no puede omitirse" in result["details"][0]


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------


def test_routing_passes_when_the_engine_matches():
    assert gate_routing_expected(_case())["passed"] is True


def test_routing_fails_on_the_wrong_engine():
    result = gate_routing_expected(_case(expected={"engine_key": "sotp"}))
    assert result["passed"] is False


def test_routing_fails_when_the_trace_engine_silently_aliases():
    case = _case(engine="holding_company", expected={"engine_key": "holding_company"})
    case["artifact"]["_routing"]["trace_engine"] = "sotp"
    result = gate_routing_expected(case)
    assert result["passed"] is False
    assert "alias" in result["details"][0]


def test_a_declared_trace_engine_alias_is_accepted_and_recorded():
    case = _case(engine="holding_company", expected={
        "engine_key": "holding_company", "trace_engine": "sotp",
    })
    case["artifact"]["_routing"]["trace_engine"] = "sotp"
    assert gate_routing_expected(case)["passed"] is True


def test_declared_trace_engine_must_match_what_the_motor_reports():
    case = _case(expected={"engine_key": "standard_dcf", "trace_engine": "sotp"})
    assert gate_routing_expected(case)["passed"] is False


# --------------------------------------------------------------------------
# evidencia
# --------------------------------------------------------------------------


def test_trace_with_fact_ids_and_periods_passes():
    assert gate_trace_records_evidence(_case())["passed"] is True


def test_empty_fact_ids_fail():
    case = _case(_artifact(trace={**_artifact()["trace"], "fact_ids": {"revenue": None}}))
    assert gate_trace_records_evidence(case)["passed"] is False


def test_empty_periods_fail():
    case = _case(_artifact(trace={**_artifact()["trace"], "periods": {"revenue": None}}))
    assert gate_trace_records_evidence(case)["passed"] is False


def test_missing_model_version_fails():
    trace = {**_artifact()["trace"]}
    del trace["model_version"]
    assert gate_trace_records_evidence(_case(_artifact(trace=trace)))["passed"] is False


def test_declaring_the_evidence_gate_on_a_case_that_publishes_nothing_fails():
    """Sin esta regla, omitir el trace seri la forma mas barata de callar la puerta."""
    result = gate_trace_records_evidence(_case(_refusal()))
    assert result["passed"] is False
    assert "no publica valor" in result["details"][0]


# --------------------------------------------------------------------------
# base ADR
# --------------------------------------------------------------------------


def test_adr_gate_passes_without_a_ratio():
    assert gate_adr_ratio_basis(_case())["passed"] is True


def test_adr_gate_passes_with_a_ratio_when_everything_is_converted():
    artifact = _artifact(
        current_price=200.0,
        # #2338: margen de seguridad estandar (V - P) / V sobre la base comparable.
        margin_of_safety=(15.0 - 25.0) / 15.0,
        adr_ratio=8.0,
        value_per_share_basis="ordinary_share",
        comparable_price_basis="ordinary_share",
        listed_share_values={
            "bear": 80.0, "base": 120.0, "bull": 160.0, "expected": 120.0,
        },
        trace={**_artifact()["trace"], "comparable_price": 25.0},
    )
    case = _case(artifact, {"adr_ratio": 8.0})
    assert gate_adr_ratio_basis(case)["passed"] is True


def test_adr_gate_fails_when_listed_values_are_not_scaled_by_the_ratio():
    artifact = _artifact(
        adr_ratio=8.0,
        value_per_share_basis="ordinary_share",
        comparable_price_basis="ordinary_share",
        listed_share_values={
            "bear": 10.0, "base": 15.0, "bull": 20.0, "expected": 15.0,
        },
        trace={**_artifact()["trace"], "comparable_price": 12.0},
    )
    result = gate_adr_ratio_basis(_case(artifact, {"adr_ratio": 8.0}))
    assert result["passed"] is False
    assert "listed_share_values" in result["details"][0]


def test_adr_gate_fails_when_the_quote_is_not_converted_to_the_ordinary_basis():
    artifact = _artifact(
        adr_ratio=8.0,
        value_per_share_basis="ordinary_share",
        comparable_price_basis="listed_share",
        listed_share_values={
            "bear": 80.0, "base": 120.0, "bull": 160.0, "expected": 120.0,
        },
        trace={**_artifact()["trace"], "comparable_price": 200.0},
    )
    assert gate_adr_ratio_basis(_case(artifact, {"adr_ratio": 8.0}))["passed"] is False


def test_adr_gate_fails_on_an_undeclared_ratio():
    artifact = _artifact(
        adr_ratio=8.0,
        value_per_share_basis="ordinary_share",
        comparable_price_basis="ordinary_share",
        listed_share_values={
            "bear": 80.0, "base": 120.0, "bull": 160.0, "expected": 120.0,
        },
        trace={**_artifact()["trace"], "comparable_price": 25.0},
    )
    result = gate_adr_ratio_basis(_case(artifact))
    assert result["passed"] is False


def test_adr_gate_fails_when_listed_values_are_published_without_a_ratio():
    artifact = _artifact(
        listed_share_values={
            "bear": 10.0, "base": 15.0, "bull": 20.0, "expected": 15.0,
        }
    )
    assert gate_adr_ratio_basis(_case(artifact))["passed"] is False
