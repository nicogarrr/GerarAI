"""Campos profesionales de la tesis (hipotesis, catalizadores, invalidacion,
probabilidades): helpers deterministicos, sin DB ni red.

Run from data-engine/:
    pytest tests/test_thesis_professional_fields.py -v
"""

from __future__ import annotations

from app.models import Company
from app.services.thesis_service import ThesisService


def _company() -> Company:
    return Company(ticker="ABC", name="ABC Corp", company_type="compounders", valuation_model="dcf")


def test_hypothesis_below_base_value() -> None:
    service = ThesisService()
    valuation = {
        "current_price": 80.0,
        "base_value": 100.0,
        "margin_of_safety": 0.2,
        "reverse_dcf": {"required_revenue_growth": 0.12},
    }
    hypothesis = service._hypothesis(_company(), valuation)
    # MoS = base/price - 1: se nombra explicitamente (F341).
    assert "margen de seguridad del 20,0 %" in hypothesis
    assert "100.00" in hypothesis
    assert "12,0 %" in hypothesis


def test_hypothesis_above_base_value() -> None:
    service = ThesisService()
    valuation = {"current_price": 120.0, "base_value": 100.0, "margin_of_safety": -0.2}
    hypothesis = service._hypothesis(_company(), valuation)
    assert "margen de seguridad del -20,0 %" in hypothesis
    assert "descuenta más" in hypothesis


def test_hypothesis_negative_base_has_no_percentage() -> None:
    service = ThesisService()
    valuation = {"current_price": 58.45, "base_value": -84.7, "margin_of_safety": -2.49}
    hypothesis = service._hypothesis(_company(), valuation)
    assert "-249%" not in hypothesis
    assert "no es interpretable" in hypothesis
    assert "no sostiene" not in hypothesis
    assert "-84.70" in hypothesis


def test_hypothesis_incomplete_data_is_honest() -> None:
    service = ThesisService()
    hypothesis = service._hypothesis(_company(), {"current_price": None, "base_value": None, "margin_of_safety": None})
    assert "en formación" in hypothesis


def test_catalysts_from_earnings_calendar() -> None:
    service = ThesisService()
    evidence = {
        "sources": {
            "earnings": {"status": "ok", "next_date": "2026-10-28", "time": "amc", "eps_forecast": 1.23}
        }
    }
    catalysts = service._catalysts(evidence)
    assert len(catalysts) == 1
    assert catalysts[0]["date"] == "2026-10-28"
    assert catalysts[0]["eps_forecast"] == 1.23


def test_catalysts_empty_without_known_dates() -> None:
    service = ThesisService()
    assert service._catalysts({}) == []
    assert service._catalysts({"sources": {"earnings": {"status": "error"}}}) == []


def test_invalidation_criteria_from_model_data() -> None:
    service = ThesisService()
    valuation = {
        "current_price": 80.0,
        "base_value": 100.0,
        "margin_of_safety": 0.2,
        "reverse_dcf": {"required_revenue_growth": 0.12},
        "moat": {"moats": [{"type": "switching_costs", "trend": "declining"}]},
    }
    criteria = service._invalidation_criteria(_company(), valuation)
    assert any("margen de seguridad" in c for c in criteria)
    assert any("12.0%" in c for c in criteria)
    assert any("switching_costs" in c for c in criteria)


def test_invalidation_fallback_is_honest() -> None:
    service = ThesisService()
    criteria = service._invalidation_criteria(_company(), {})
    assert criteria == ["Tesis en formación: sin criterios automáticos hasta completar la valoración."]


def test_scenario_probabilities_from_model() -> None:
    service = ThesisService()
    model = {"scenarios": {"bear": {"probability": 0.25}, "base": {"probability": 0.5}, "bull": {"probability": 0.25}}}
    assert service._scenario_probabilities(model) == {"bear": 0.25, "base": 0.5, "bull": 0.25}
    assert service._scenario_probabilities({}) is None
    assert service._scenario_probabilities({"scenarios": {"bear": {}}}) is None


def test_visible_copy_has_accents_and_no_english_label() -> None:
    """F13/B14: 'Hipotesis'/'valoracion' sin tilde y 'Missing valuation inputs' en ingles."""
    import inspect

    from app.services import thesis_service

    source = inspect.getsource(thesis_service)
    assert "Missing valuation inputs" not in source
    assert "Faltan entradas de valoración" in source
    assert "Hipotesis en formacion" not in source
    hypothesis = ThesisService()._hypothesis(_company(), {"current_price": None, "base_value": None, "margin_of_safety": None})
    assert "Hipótesis en formación" in hypothesis


def test_banda_y_porcentajes_del_memo_en_castellano() -> None:
    from app.services.thesis_service import _band_es, _pct_es

    assert _band_es([0.16999999999999998, 0.25, 0.3]) == "17 % / 25 % / 30 %"
    assert _band_es(None) == "N/D"
    assert _pct_es(0.25) == "25 %" and _pct_es(0.155) == "15,5 %"
