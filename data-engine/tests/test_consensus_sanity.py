"""Contraste con el consenso: conciliación dato a dato por encima del 35 %.

Feature aprobada por Nico (regla 1 de gerarai-asts3/REPORT.md §8). DCF
sintético; nada por ticker. Cubre el umbral (y el rango de objetivos), la
cascada input a input con el mismo motor, «explicado» frente a «revisar»,
pasos no calculables, etiquetas, motores no DCF y el flag.
"""

from __future__ import annotations

import pytest

from app.valuation.consensus_sanity import (
    REVIEW_BLOCKER,
    StepLabel,
    apply_consensus_sanity,
    assess,
    consensus_sanity_for_dcf,
    needs_reconciliation,
)
from app.valuation.normalized_fcf import run_path_dcf

YEARS = 5


def _trace(**over) -> dict:
    inputs: dict = dict(
        revenue=1_000.0,
        growth_path=[0.0] * YEARS,
        margin_path=[0.08] * YEARS,
        wacc=0.10,
        terminal_growth=0.0,
        net_debt=0.0,
        shares_outstanding=1.0,
    )
    inputs.update(over)
    return run_path_dcf(**inputs).trace


def _valuation(**over) -> dict:
    trace = _trace(**over)
    return {
        "status": "ok",
        "publishable": True,
        "publication_blockers": [],
        "trace": {"engine": "standard_dcf", "scenarios": {"base": {"trace": trace}}},
    }


def _value(**over) -> float:
    return run_path_dcf(
        **{
            "revenue": 1_000.0,
            "growth_path": [0.0] * YEARS,
            "margin_path": [0.08] * YEARS,
            "wacc": 0.10,
            "terminal_growth": 0.0,
            "net_debt": 0.0,
            "shares_outstanding": 1.0,
            **over,
        }
    ).value_per_share


# ------------------------------------------------------------------ umbral
@pytest.mark.parametrize(
    ("ours", "consensus", "low", "high", "needed", "outside"),
    [
        (70.0, 100.0, None, None, False, False),  # −30 %
        (64.0, 100.0, None, None, True, False),  # −36 %
        (136.0, 100.0, None, None, True, False),  # +36 %
        (90.0, 100.0, 95.0, 140.0, True, True),  # dentro del 35 % pero fuera del rango
    ],
)
def test_umbral_35_y_rango_de_objetivos(ours, consensus, low, high, needed, outside) -> None:
    assert needs_reconciliation(ours, consensus, target_low=low, target_high=high) == (needed, outside)


def test_sin_consenso_o_sin_valor() -> None:
    assert assess(10.0, None).status == "sin_consenso"
    assert assess(10.0, 0.0).status == "sin_consenso"
    assert assess(None, 10.0).status == "no_aplica"


def test_dentro_del_umbral_no_pide_conciliacion() -> None:
    ours = _value()
    sanity = consensus_sanity_for_dcf(_valuation(), consensus=ours * 1.2, analyst_inputs={"margin": 0.1})
    assert sanity.status == "dentro" and sanity.steps == []


# ------------------------------------------------------------------ cascada
def test_diferencia_explicada_input_a_input() -> None:
    theirs = {"margin": 0.12, "wacc": 0.09}
    consensus = _value(margin_path=[0.12] * YEARS, wacc=0.09)
    sanity = consensus_sanity_for_dcf(
        _valuation(),
        consensus=consensus,
        analyst_inputs=theirs,
        sources={"margin": "Firm A"},
        labels={"margin": StepLabel("aceptamos", "margen de pares"), "wacc": StepLabel("inventada", "x")},
    )
    assert sanity.status == "explicado", sanity.reason
    assert [s.input_key for s in sanity.steps] == ["margin", "wacc"]
    assert sanity.residual == pytest.approx(0.0, abs=1e-6)
    assert sum(s.effect or 0 for s in sanity.steps) == pytest.approx(consensus - _value())
    assert sanity.main_driver == "margin"
    margin_step = sanity.steps[0]
    assert (margin_step.label, margin_step.reason, margin_step.source) == (
        "aceptamos",
        "margen de pares",
        "Firm A",
    )
    assert sanity.steps[1].label == "abierta"  # etiqueta desconocida → abierta
    payload = sanity.as_dict()
    assert payload["steps"][0]["name"] == "margen de flujo de caja libre"
    assert payload["steps"][0]["effect_per_share"] > 0


def test_diferencia_sin_explicar_queda_revisar() -> None:
    sanity = consensus_sanity_for_dcf(_valuation(), consensus=_value() * 3, analyst_inputs={"margin": 0.09})
    assert sanity.status == "revisar"
    assert sanity.residual_share is not None and sanity.residual_share > 0.25
    assert "sin explicar" in (sanity.reason or "")


def test_sin_inputs_de_analistas_queda_revisar() -> None:
    sanity = consensus_sanity_for_dcf(_valuation(), consensus=_value() * 2, analyst_inputs={})
    assert sanity.status == "revisar" and sanity.steps == []
    assert "sin inputs" in (sanity.reason or "")


def test_paso_no_calculable_no_se_aplica() -> None:
    theirs = {"margin": 0.16, "terminal_growth": 0.2}  # g ≥ WACC: el motor no puede
    consensus = _value(margin_path=[0.16] * YEARS)
    sanity = consensus_sanity_for_dcf(_valuation(), consensus=consensus, analyst_inputs=theirs)
    bad = [s for s in sanity.steps if s.input_key == "terminal_growth"][0]
    assert bad.value_after is None and bad.error
    assert sanity.status == "explicado"


def test_trayectorias_de_otra_longitud_se_ignoran() -> None:
    sanity = consensus_sanity_for_dcf(
        _valuation(), consensus=_value() * 2, analyst_inputs={"growth": [0.1, 0.1], "margin": [0.2] * YEARS}
    )
    assert [s.input_key for s in sanity.steps] == ["margin"]


def test_motor_no_dcf_pide_conciliacion_manual() -> None:
    valuation = {"trace": {"engine": "ddm", "scenarios": {"base": {"trace": {"method": "ddm"}}}}}
    sanity = consensus_sanity_for_dcf(valuation, consensus=100.0, our_value=40.0)
    assert sanity.status == "revisar" and "manual" in (sanity.reason or "")
    assert consensus_sanity_for_dcf(valuation, consensus=100.0, our_value=90.0).status == "dentro"


# ------------------------------------------------------------------ resultado y flag
def test_flag_apagado_no_toca_el_resultado() -> None:
    result = _valuation()
    sanity = consensus_sanity_for_dcf(result, consensus=_value() * 3, analyst_inputs={})
    out = apply_consensus_sanity(result, sanity, enabled=False)
    assert "consensus_reconciliation" not in out["trace"] and out["publishable"] is True


def test_flag_por_defecto_es_el_de_la_config(monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "expert_team_enabled", False, raising=False)
    result = _valuation()
    out = apply_consensus_sanity(result, assess(1.0, 10.0))
    assert "consensus_reconciliation" not in out["trace"]


def test_revisar_bloquea_y_queda_en_la_traza() -> None:
    result = _valuation()
    sanity = consensus_sanity_for_dcf(result, consensus=_value() * 3, analyst_inputs={"margin": 0.09})
    out = apply_consensus_sanity(result, sanity, enabled=True)
    assert out["trace"]["consensus_reconciliation"]["status"] == "revisar"
    assert out["review_status"] == "revisar"
    assert out["publishable"] is False and out["publication_blockers"] == [REVIEW_BLOCKER]
    apply_consensus_sanity(out, sanity, enabled=True)
    assert out["publication_blockers"] == [REVIEW_BLOCKER]  # sin duplicar


def test_explicado_solo_deja_la_conciliacion() -> None:
    result = _valuation()
    consensus = _value(margin_path=[0.16] * YEARS)
    sanity = consensus_sanity_for_dcf(result, consensus=consensus, analyst_inputs={"margin": 0.16})
    out = apply_consensus_sanity(result, sanity, enabled=True)
    assert out["trace"]["consensus_reconciliation"]["status"] == "explicado"
    assert out["publishable"] is True and "review_status" not in out
