"""Línea informativa de pagos en acciones (SBC) junto al DCF estándar (gerarai-dcavalor2/2b, 8-nov-2026)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base
from app.valuation.normalized_fcf import run_path_dcf
from app.valuation.sbc_note import sbc_adjustment


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _F:
    def __init__(self, value):
        self.value = value


def _inputs(margin=0.20):
    return {
        "revenue": 1000.0,
        "growth_path": [0.05] * 5,
        "margin_path": [margin] * 5,
        "wacc": 0.10,
        "terminal_growth": 0.03,
        "net_debt": 0.0,
        "shares_outstanding": 100.0,
    }


def _dcf_result(expected_scale=1.0):
    scenarios = {}
    for name, prob, margin in (("bear", 0.25, 0.15), ("base", 0.5, 0.20), ("bull", 0.25, 0.25)):
        value = run_path_dcf(**_inputs(margin)).value_per_share
        scenarios[name] = {
            "definition": {"probability": prob},
            "value_per_share": value,
            "trace": {"inputs": _inputs(margin)},
        }
    expected = sum(s["definition"]["probability"] * s["value_per_share"] for s in scenarios.values())
    return {
        "expected_value": expected * expected_scale,
        "value_currency": "USD",
        "trace": {"engine": "standard_dcf", "scenarios": scenarios},
    }


def _history(sbc, revenue=1000.0, ocf=300.0, capex=-100.0, year=2025):
    return {
        year: {
            "revenue": _F(revenue),
            "operating_cash_flow": _F(ocf),
            "capital_expenditure": _F(capex),
            "stock_based_compensation": _F(sbc),
        }
    }


def test_sbc_line_recomputes_every_scenario_with_sbc_as_an_expense():
    result = _dcf_result()
    out = sbc_adjustment(result, _history(sbc=50.0))  # SBC 25 % del FCF (200), 5 % de las ventas
    assert out is not None
    assert out["sbc_share_of_fcf"] == 0.25 and out["sbc_to_revenue"] == 0.05 and out["fiscal_year"] == 2025
    expected_after = sum(
        p * run_path_dcf(**{**_inputs(m), "margin_path": [m - 0.05] * 5}).value_per_share
        for p, m in ((0.25, 0.15), (0.5, 0.20), (0.25, 0.25))
    )
    assert out["value_after_sbc"] == pytest.approx(expected_after)
    assert out["value_after_sbc"] < result["expected_value"]
    assert out["message_es"].startswith("Si se restan los pagos en acciones (25 % del FCF de 2025), el valor sería ~")
    assert out["message_es"].endswith("restarlo ordenó peor las empresas.")
    # proporción sobre el valor publicado (p. ej. en otra divisa)
    scaled = sbc_adjustment(_dcf_result(expected_scale=1.25), _history(sbc=50.0))
    assert scaled["value_after_sbc"] == pytest.approx(expected_after * 1.25)


def test_sbc_line_only_when_it_weighs_and_applies():
    assert sbc_adjustment(_dcf_result(), _history(sbc=10.0)) is None  # 5 % del FCF
    assert sbc_adjustment(_dcf_result(), _history(sbc=50.0, ocf=90.0)) is None  # FCF negativo
    assert sbc_adjustment(_dcf_result(), {}) is None
    other = {**_dcf_result(), "trace": {"engine": "reit"}}
    assert sbc_adjustment(other, _history(sbc=50.0)) is None
    negative = sbc_adjustment(_dcf_result(), _history(sbc=190.0))  # 19 % de las ventas > margen bear
    assert negative is not None
    assert negative["value_after_sbc"] is None or negative["value_after_sbc"] > 0


def test_value_company_attaches_the_sbc_line_without_changing_the_value(db):
    from app.services.valuation_service import ValuationService
    from tests.test_valgrandes_normalized_fcf import AMZN, M, _fact, _seed

    company = _seed(db, "SBCX", AMZN, shares=10_827 * M, net_debt=-5_233 * M, price=251.36, wacc=0.11141566)
    for year, sbc in ((2023, 24_023), (2024, 22_011), (2025, 19_500)):
        _fact(db, company, "stock_based_compensation", sbc * M, year)
    db.commit()
    result = ValuationService().value_company(db, company)
    assert result["trace"]["engine"] == "standard_dcf"
    assert "market_calibration" not in result["trace"]
    sbc = result["sbc_adjustment"]
    assert sbc["fiscal_year"] == 2025 and sbc["sbc_share_of_fcf"] == pytest.approx(19_500 / (139_514 - 131_819), rel=1e-3)
    assert sbc["value_after_sbc"] is None or sbc["value_after_sbc"] < result["expected_value"]


def test_api_schema_keeps_the_sbc_line():
    from app.schemas.api import ValuationResponse

    out = ValuationResponse(ticker="X", model_type="dcf", sbc_adjustment={"message_es": "x"}).model_dump()
    assert out["sbc_adjustment"]["message_es"] == "x"
