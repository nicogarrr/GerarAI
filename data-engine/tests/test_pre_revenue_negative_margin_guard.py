"""Un margen FCF reportado negativo no produce valores por accion negativos."""

from types import SimpleNamespace

from app.valuation.engines.base import ValuationContext
from app.valuation.engines.pre_revenue import PreRevenueScenarioEngine


class _Snap:
    # FinancialSnapshot.excluded_present (928a2cec): los motores lo leen siempre.
    excluded_present: list = []
    coherent = True
    as_of_period = None
    income_statement = None
    balance_sheet = None
    shares_period = None
    warnings: list = []
    facts: dict = {}
    missing_inputs: list = []

    def __init__(self, values):
        self._v = values

    def value(self, metric):
        return self._v.get(metric)

    def fact_ids(self):
        return {}

    def periods(self):
        return {}


def _run(values):
    company = SimpleNamespace(
        id=None,
        ticker="BURN",
        valuation_model="probability_weighted_scenarios+dilution",
        company_type="space_telecom_pre_fcf",
        factor_tags=["pre_fcf"],
        special_risks=[],
    )
    ctx = ValuationContext(
        db=None, company=company, snapshot=_Snap(values), current_price=63.12, engine_key="pre_revenue"
    )
    return PreRevenueScenarioEngine().value(ctx)


def test_negative_fcf_margin_publishes_no_negative_per_share_value():
    result = _run(
        {
            "revenue": 70_918_000.0,
            "shares_diluted": 255_982_592.0,
            "fcf_margin": -15.46,
            "net_debt": 100_000_000.0,
        }
    )
    assert result["status"] == "insufficient_data"
    assert result["publishable"] is False
    assert "non_negative_fcf_margin" in result["missing_inputs"]
    for field in ("bear_value", "base_value", "bull_value", "expected_value", "margin_of_safety"):
        assert result[field] is None, field
