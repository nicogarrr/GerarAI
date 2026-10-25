"""El rango indicativo pre-revenue no puede contradecir una quema de caja reportada."""

from types import SimpleNamespace

from app.valuation.engines.base import ValuationContext
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine


class _Snap:
    # FinancialSnapshot.excluded_present (928a2cec): los motores lo leen siempre.
    excluded_present: list = []
    coherent = False
    as_of_period = None
    income_statement = None
    balance_sheet = None
    shares_period = None
    warnings: list = []
    facts: dict = {}

    def __init__(self, values, missing=None):
        self._v = values
        self.missing_inputs = missing or ["revenue_history_two_periods"]

    def value(self, metric):
        return self._v.get(metric)

    def fact_ids(self):
        return {}

    def periods(self):
        return {}


def _company():
    return SimpleNamespace(
        ticker="BURN",
        valuation_model="space_network",
        company_type="space",
        factor_tags=["pre_fcf"],
        special_risks=[],
    )


def _run(values):
    ctx = ValuationContext(db=None, company=_company(), snapshot=_Snap(values), current_price=58.86, engine_key="pre_revenue")
    return PreRevenueScenarioEngine().value(ctx)


def test_cash_burn_blocks_assumed_margin_range():
    result = _run(
        {"revenue": 70_918_000.0, "shares_diluted": 255_982_592.0, "operating_cash_flow": -71_517_000.0}
    )
    assert result["status"] == "insufficient_data"
    assert result["publishable"] is False
    assert result["base_value"] is None and result["bear_value"] is None
    assert result["bull_value"] is None and result["expected_value"] is None
    assert result["margin_of_safety"] is None
    assert "normalized_fcf_or_fcf_margin" in result["missing_inputs"]
    assert result["trace"]["observed_cash_burn"] == {"operating_cash_flow": -71_517_000.0}


def test_positive_cash_flow_keeps_indicative_path():
    result = _run(
        {"revenue": 70_918_000.0, "shares_diluted": 255_982_592.0, "operating_cash_flow": 5_000_000.0}
    )
    assert result["status"] == "partial"
    assert result["trace"]["valuation_basis"] == "indicative_assumptions"


def test_no_cash_flow_data_also_blocks_assumed_margin_range():
    result = _run({"revenue": 70_918_000.0, "shares_diluted": 255_982_592.0})
    assert result["status"] == "insufficient_data"
    assert result["base_value"] is None and result["expected_value"] is None
    assert result["margin_of_safety"] is None
    assert "normalized_fcf_or_fcf_margin" in result["missing_inputs"]
    assert result["trace"]["observed_cash_burn"] == {}
