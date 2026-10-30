"""Escenarios DCF con valor por acción <= 0: N/D explicado, nunca cifra negativa.

Caso real (AMZN, 30-oct-2026): margen FCF FY 1,07 %; el escenario bajista
(margen base − 6 pp) quema caja y el modelo publicaba «bear -45,82» como si
fuera una valoración. Convención d2656966 (un múltiplo negativo es N/D): el
escenario sale N/D con el motivo, el bruto queda en la traza y sigue
ponderando el esperado (bear <= base se mantiene).
"""

import pytest

from app.core.database import SessionLocal, init_db
from app.services.valuation_service import ValuationService
from tests.test_valuation_engines_refined import (
    _add_facts,
    _add_price,
    _add_traceable_wacc,
    _cleanup,
    _make_company,
)

# Margen FCF 1,1 %: el bear (margen − 6 pp) queda en −4,9 % y quema caja.
FACTS = {"revenue": 1000, "free_cash_flow": 11, "revenue_growth": 0.07, "shares_diluted": 100, "net_debt": 200}


def _value(db, ticker, facts=FACTS, tags=()):
    company = _make_company(
        db, ticker, company_type="standard", valuation_model="standard_dcf", factor_tags=list(tags)
    )
    _add_facts(db, company, facts)
    _add_price(db, company, 20.0)
    _add_traceable_wacc(db, company)
    return ValuationService().value_company(db, company)


def test_negative_bear_scenario_is_explained_nd_and_expected_keeps_ordering():
    init_db()
    db = SessionLocal()
    try:
        result = _value(db, "NDA")
        assert result["status"] == "ok"
        # El bear no se publica como cifra negativa: N/D con explicación.
        assert result["bear_value"] is None
        note = result["scenario_notes"]["bear"]
        assert "bajista" in note and "N/D" in note
        assert "quema" in note  # el margen FCF del escenario es negativo
        # El bruto queda en la traza y confirma que el bear salía negativo.
        raw_bear = result["trace"]["scenarios"]["bear"]["value_per_share_raw"]
        assert raw_bear < 0
        assert result["trace"]["scenarios"]["bear"]["value_per_share"] is None
        assert result["trace"]["scenarios"]["bear"]["value_note"] == note
        # El esperado se calcula con los brutos: pondera el bear negativo y
        # queda por debajo del base (no se infla excluyéndolo).
        assert result["base_value"] is not None and result["base_value"] > 0
        assert result["expected_value"] is not None
        assert result["trace"]["expected_value_raw"] == pytest.approx(result["expected_value"])
        # El esperado sale de los brutos (bear negativo incluido): se
        # recompute a mano con las probabilidades de la traza y coincide;
        # excluir el bear daría un esperado mayor (inflado).
        scenarios_trace = result["trace"]["scenarios"]
        raw_values = {
            name: scenarios_trace[name].get("value_per_share_raw", scenarios_trace[name]["value_per_share"])
            for name in ("bear", "base", "bull")
        }
        probs = {name: scenarios_trace[name]["definition"]["probability"] for name in ("bear", "base", "bull")}
        prob_sum = sum(probs.values())
        manual = sum(probs[name] * raw_values[name] for name in probs) / prob_sum
        assert result["expected_value"] == pytest.approx(manual)
        without_bear = (probs["base"] * raw_values["base"] + probs["bull"] * raw_values["bull"]) / (
            probs["base"] + probs["bull"]
        )
        assert result["expected_value"] < without_bear
        # Sin ratio ADR no hay conversiones por listado.
        assert result["listed_share_values"] is None
    finally:
        _cleanup(db, ["NDA"])
        db.close()


def test_positive_scenarios_have_no_notes_and_keep_values():
    init_db()
    db = SessionLocal()
    try:
        healthy = {"revenue": 1000, "free_cash_flow": 120, "revenue_growth": 0.07, "shares_diluted": 100, "net_debt": 200}
        result = _value(db, "NDB", facts=healthy)
        assert result["status"] == "ok"
        assert result["scenario_notes"] == {}
        assert result["bear_value"] is not None and result["bear_value"] > 0
        assert result["bear_value"] < result["base_value"] < result["bull_value"]
        assert "value_per_share_raw" not in result["trace"]["scenarios"]["bear"]
    finally:
        _cleanup(db, ["NDB"])
        db.close()


def test_negative_expected_value_is_explained_nd():
    """Deuda muy por encima del EV: hasta el base sale <= 0 y el esperado es N/D."""
    init_db()
    db = SessionLocal()
    try:
        leveraged = {"revenue": 1000, "free_cash_flow": 11, "revenue_growth": 0.07, "shares_diluted": 100, "net_debt": 100000}
        result = _value(db, "NDC", facts=leveraged)
        assert result["status"] == "ok"
        assert result["expected_value"] is None
        assert "expected" in result["scenario_notes"]
        assert "N/D" in result["scenario_notes"]["expected"]
        assert result["trace"]["expected_value_raw"] is not None
        assert result["margin_of_safety"] is None
    finally:
        _cleanup(db, ["NDC"])
        db.close()
