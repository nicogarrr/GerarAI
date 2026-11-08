"""Línea «crecimiento que descuenta el precio frente al histórico» (gerarai-dcavalor2b, 8-nov-2026)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.valuation.implied_growth_note import implied_growth_vs_history


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _result(implied=0.14, cagr=0.09, engine="standard_dcf", out_of_bounds=False):
    return {
        "reverse_dcf": {"required_revenue_growth": implied, "out_of_bounds": out_of_bounds},
        "trace": {
            "engine": engine,
            "growth_semantics": {
                "historical_revenue_cagr": None if cagr is None else {"value": cagr, "from_year": 2022, "to_year": 2025}
            },
        },
    }


def test_line_compares_priced_in_growth_with_history():
    note = implied_growth_vs_history(_result())
    assert note is not None
    assert note["implied_revenue_growth"] == 0.14 and note["historical_revenue_cagr"] == 0.09
    assert note["gap"] == pytest.approx(0.05)
    assert note["message_es"] == (
        "Crecimiento que descuenta el precio: 14,0 % anual de ingresos durante 5 años; en los últimos "
        "3 ejercicios ha crecido un 9,0 % anual (FY2022–FY2025). Dato informativo: no cambia la señal."
    )
    assert note["message_en"].startswith("Growth priced in: 14.0% a year in revenue for 5 years")


def test_no_line_without_both_numbers_or_for_other_engines():
    assert implied_growth_vs_history(_result(cagr=None)) is None
    assert implied_growth_vs_history(_result(implied=None)) is None
    assert implied_growth_vs_history(_result(out_of_bounds=True)) is None
    assert implied_growth_vs_history(_result(engine="reit")) is None
    assert implied_growth_vs_history({}) is None


def test_value_company_attaches_it_without_changing_the_value(db):
    from app.services.valuation_service import ValuationService
    from tests.test_valgrandes_normalized_fcf import AMZN, M, _seed

    company = _seed(db, "IGX", AMZN, shares=10_827 * M, net_debt=-5_233 * M, price=251.36, wacc=0.11141566)
    result = ValuationService().value_company(db, company)
    assert result["trace"]["engine"] == "standard_dcf"
    note = result["implied_growth"]
    semantics = result["trace"]["growth_semantics"]
    assert note["implied_revenue_growth"] == semantics["market_implied_revenue_growth"]
    assert note["historical_revenue_cagr"] == semantics["historical_revenue_cagr"]["value"]
    # el párrafo del DCF inverso ya no repite el histórico: lo dice esta línea
    assert "El histórico es" not in result["reverse_dcf"]["explanation_es"]


def test_api_schema_keeps_the_line():
    from app.schemas.api import ValuationResponse

    out = ValuationResponse(ticker="X", model_type="dcf", implied_growth={"message_es": "x"}).model_dump()
    assert out["implied_growth"]["message_es"] == "x"
