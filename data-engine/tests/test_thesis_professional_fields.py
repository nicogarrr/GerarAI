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
    assert any("12,0 %" in c for c in criteria)
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

def test_hypothesis_names_expected_value_as_margin_basis() -> None:
    """MSFT: MoS = valor esperado/precio - 1; con base 309,10 no sale -31%."""
    service = ThesisService()
    valuation = {
        "current_price": 529.05,
        "base_value": 309.10,
        "expected_value": 365.0,
        "margin_of_safety": 365.0 / 529.05 - 1,
    }
    hypothesis = service._hypothesis(_company(), valuation)
    assert "margen de seguridad del -31,0 % respecto al valor esperado (365.00)" in hypothesis
    assert "escenario base" not in hypothesis


def test_hypothesis_states_margin_basis_of_reverse_dcf() -> None:
    service = ThesisService()
    valuation = {
        "current_price": 80.0,
        "base_value": 100.0,
        "margin_of_safety": 0.2,
        "reverse_dcf": {"required_revenue_growth": 0.319, "fcf_margin": 0.202},
    }
    hypothesis = service._hypothesis(_company(), valuation)
    assert "31,9 % anual con un margen FCF del 20,2 %." in hypothesis

def test_hypothesis_partial_keeps_number_but_labels_it_indicative() -> None:
    """B6: un -95 % sobre supuestos no se oculta; se etiqueta como indicativo."""
    service = ThesisService()
    valuation = {
        "current_price": 40.66,
        "base_value": 1.95,
        "expected_value": 1.95,
        "margin_of_safety": -0.952,
        "status": "partial",
        "publishable": False,
    }
    hypothesis = service._hypothesis(_company(), valuation)
    assert hypothesis.startswith("Valoración indicativa sobre supuestos: ")
    assert "margen de seguridad del -95,2 %" in hypothesis
    assert "1.95" in hypothesis


def test_hypothesis_not_publishable_flag_alone_labels_indicative() -> None:
    service = ThesisService()
    valuation = {
        "current_price": 120.0,
        "base_value": 100.0,
        "margin_of_safety": -0.2,
        "publishable": False,
    }
    hypothesis = service._hypothesis(_company(), valuation)
    assert hypothesis.startswith("Valoración indicativa sobre supuestos: ")


def test_hypothesis_publishable_has_no_indicative_prefix() -> None:
    service = ThesisService()
    valuation = {
        "current_price": 120.0,
        "base_value": 100.0,
        "margin_of_safety": -0.2,
        "status": "ok",
        "publishable": True,
    }
    hypothesis = service._hypothesis(_company(), valuation)
    assert not hypothesis.startswith("Valoración indicativa")


def test_notice_es_never_shows_raw_english() -> None:
    from app.services.thesis_service import _notice_es

    indicativo = _notice_es({"notice": "INDICATIVE RANGE — uses assumed FCF margin (base 25%)"})
    assert indicativo.startswith("RANGO INDICATIVO")
    assert "INDICATIVE" not in indicativo
    orientacion = _notice_es({"notice": "Valuation computed on inputs that are not traceable"})
    assert orientacion.startswith("Valoración calculada")
    assert _notice_es({"notice": "Something new in English"}) == ""
    assert _notice_es({}) == ""


def test_is_annual_rejects_quarter_period_with_date_prefix() -> None:
    from types import SimpleNamespace

    from app.services.long_term_model_service import _is_annual

    assert not _is_annual(SimpleNamespace(fiscal_quarter=None, period="2022-12-31:Q1"))
    assert _is_annual(SimpleNamespace(fiscal_quarter=None, period="2025-09-27:FY"))
    assert _is_annual(SimpleNamespace(fiscal_quarter=None, period=None))
def test_news_dedupe_collapses_same_headline_from_several_agencies() -> None:
    from types import SimpleNamespace

    from app.services.thesis_evidence_service import _dedupe_news_rows

    titles = [
        "ASTS Investors Have Opportunity to Lead AST SpaceMobile, Inc. Securities Fraud Lawsuit",
        "ASTS Investors Have Opportunity to Lead AST SpaceMobile, Inc. Securities Fraud Lawsuit with SBS Law",
        "AST SpaceMobile (ASTS) Stock May Be Priced For Perfection",
    ]
    rows = [SimpleNamespace(title=t) for t in titles]
    kept = _dedupe_news_rows(rows, 5, "ASTS")
    assert [r.title for r in kept] == [titles[0], titles[2]]
    assert len(_dedupe_news_rows(rows, 1, "ASTS")) == 1


def test_invalidation_grounded_when_price_already_above_base() -> None:
    # Observado 2026-10-26 (objeto real): precio 642.62, base 565.21,
    # esperado 656.45, mos +2,2 % = respecto al ESPERADO, no al escenario
    # base. El criterio grounded declara «sin margen respecto al escenario
    # base» y mantiene el margen respecto al esperado como benchmark aparte.
    service = ThesisService()
    valuation = {
        "current_price": 642.62,
        "base_value": 565.21,
        "expected_value": 656.45,
        "margin_of_safety": 0.0215,
    }
    criteria = service._invalidation_criteria(_company(), valuation)
    assert any(
        "ya supera el valor del escenario base" in c
        and "sin margen respecto al escenario base" in c
        and "642.62" in c and "565.21" in c
        for c in criteria
    )
    assert any(
        "valor esperado (656.45)" in c and "2,1 %" in c
        and "no son el mismo margen" in c
        for c in criteria
    )
    assert not any("no hay margen de seguridad" in c for c in criteria)
    assert not any("supera de forma sostenida" in c for c in criteria)


def test_invalidation_mos_fallback_without_price() -> None:
    service = ThesisService()
    criteria = service._invalidation_criteria(
        _company(), {"base_value": 100.0, "margin_of_safety": 0.2})
    assert any("supera de forma sostenida el valor base (100.00)" in c for c in criteria)
