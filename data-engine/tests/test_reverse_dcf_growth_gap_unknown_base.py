"""Reverse DCF: sin crecimiento base conocido no se publica una brecha."""

from types import SimpleNamespace

from app.services.long_term_model_service import LongTermModelService


def _run(base_growth):
    service = LongTermModelService()
    assumptions = {
        "fcf_margin": SimpleNamespace(value=0.15, source_fact_ids=[]),
        "wacc": SimpleNamespace(value=0.1, source_fact_ids=[]),
        "terminal_growth": SimpleNamespace(value=0.02, source_fact_ids=[]),
        "revenue_growth": SimpleNamespace(value=base_growth, source_fact_ids=[]),
    }
    service._value_for_year = lambda facts, year: {  # type: ignore[method-assign]
        "revenue": 100.0, "shares_diluted": 10.0, "net_debt": 0.0,
    }[facts]
    return service._reverse_dcf(
        current_price=40.65,
        assumptions=assumptions,
        fact_cache={"revenue": "revenue", "shares_diluted": "shares_diluted", "net_debt": "net_debt"},
        horizon=5,
        source_year=2025,
    )


def test_brecha_sin_crecimiento_base_es_none_no_el_exigido_entero():
    result = _run(None)
    assert result.get("required_revenue_growth") is not None
    assert result["base_revenue_growth"] is None
    # Antes: required - 0 => la brecha publicada era el crecimiento exigido.
    assert result["growth_gap_vs_base"] is None


def test_brecha_con_crecimiento_base_conocido():
    result = _run(0.05)
    assert result["growth_gap_vs_base"] == result["required_revenue_growth"] - 0.05
