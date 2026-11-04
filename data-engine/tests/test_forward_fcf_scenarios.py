from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.valuation.forward_fcf import ForwardScenario, value_forward_scenario, value_forward_scenarios


def scenario(name="base", multiple="20"):
    return ForwardScenario(name, Decimal(100), Decimal(multiple), Decimal(".10"), 2,
                           Decimal(10), "USD", "enterprise", Decimal(50), date(2026, 11, 4),
                           dict.fromkeys(("forward_fcf", "exit_multiple", "discount_rate", "shares", "net_debt"), "explicit synthetic assumption"))


def test_ev_discount_then_present_net_debt_bridge():
    out = value_forward_scenario(scenario())
    assert abs(out["value_per_share"] - (Decimal(2000)/Decimal("1.21")-50)/10) < Decimal("1e-20")
    assert out["method"] == "EV_FCF_discounted_at_WACC"


def test_equity_fcf_never_subtracts_debt_twice():
    assert value_forward_scenario(replace(scenario(), basis="equity"))["value_per_share"] is None
    out = value_forward_scenario(replace(scenario(), basis="equity", net_debt=None))
    assert abs(out["value_per_share"] - Decimal(200)/Decimal("1.21")) < Decimal("1e-20")


def test_missing_and_absurd_inputs_fail_closed():
    for changes in ({"net_debt": None}, {"forward_fcf": Decimal("NaN")}, {"years": 10},
                    {"shares": Decimal(0)}, {"evidence": {}}):
        assert value_forward_scenario(replace(scenario(), **changes))["value_per_share"] is None
    out = value_forward_scenario(replace(scenario(), exit_multiple=Decimal(100)))
    assert out["status"] == "orientation" and not out["publishable"]


def test_scenarios_visible_without_reordering_or_averaging():
    rows = [scenario("bull", "30"), scenario("bear", "10"), scenario()]
    out = value_forward_scenarios(rows)
    assert out["status"] == "ok"
    assert [r["name"] for r in out["scenarios"]] == ["bear", "base", "bull"]
    assert "expected_value" not in out
    assert value_forward_scenarios([scenario("bear", "30"), scenario(), scenario("bull", "10")])["status"] == "invalid"
    assert value_forward_scenarios(rows[:2])["status"] == "invalid"
    assert value_forward_scenarios([*rows[:2], replace(scenario(), currency="EUR")])["status"] == "invalid"
