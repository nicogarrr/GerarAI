"""Parity between the sample company universe and its thesis frameworks."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import Company
from app.services.company_framework import resolve_company_framework
from app.services.driver_operating_model import FORMULAS, DriverOperatingModel


def _company(
    ticker: str,
    company_type: str = "research_candidate",
    industry: str = "Unknown",
    tags: list[str] | None = None,
    valuation_model: str = "unassigned",
) -> Company:
    return Company(
        ticker=ticker,
        name=ticker,
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry=industry,
        company_type=company_type,
        valuation_model=valuation_model,
        special_sources=[],
        special_risks=[],
        factor_tags=tags or [],
    )


@pytest.mark.parametrize(
    ("ticker", "company_type", "industry", "tags", "expected"),
    [
        ("CHTR", "research_candidate", "Telecom", [], "subscriber"),
        ("BFIT.AS", "research_candidate", "Fitness", [], "subscriber"),
        ("NFLX", "subscriber_media", "Streaming entertainment", ["media", "subscriber", "fcf"], "subscriber"),
        ("ASTS", "space_telecom_pre_fcf", "Satellite telecom", ["space", "speculative", "pre_fcf", "telecom"], "space_network"),
        ("META", "ai_big_tech", "Social platforms", ["ai", "ads", "platform", "quality"], "advertising_platform"),
        ("RKLB", "space_defense_growth", "Aerospace and defense", ["space", "defense", "growth", "sotp"], "space_defense"),
        ("BN", "asset_manager_holding", "Asset management and holdings", ["financials", "sotp", "rates"], "holding_asset_manager"),
        ("PLTR", "software_ai_platform", "Data analytics software", ["ai", "software", "government"], "software_ai"),
        ("ABCL", "biotech_pre_fcf", "Pharmaceutical preparations (SIC 2834)", ["healthcare", "biotech", "ai_biology", "speculative", "pre_fcf"], "biotech_pre_fcf"),
        ("AMZN", "ai_big_tech", "Ecommerce and cloud", ["ai", "cloud", "ecommerce", "quality"], "generic_fcf"),
        ("TSLA", "auto_energy_optionality", "Automobiles", ["auto", "ai", "energy", "optionality"], "auto_energy_optionality"),
        ("AUQNUE", "research_candidate", "Unknown", [], "generic_fcf"),
    ],
)
def test_sample_tickers_resolve_to_the_expected_framework(
    ticker: str,
    company_type: str,
    industry: str,
    tags: list[str],
    expected: str,
) -> None:
    framework = resolve_company_framework(
        _company(ticker, company_type=company_type, industry=industry, tags=tags)
    )
    assert framework.key == expected


def test_tsla_stays_auto_energy_optionality_despite_the_ai_tag() -> None:
    company = _company(
        "TSLA",
        company_type="auto_energy_optionality",
        industry="Automobiles",
        tags=["auto", "ai", "energy", "optionality"],
    )
    assert "ai" in company.factor_tags
    assert resolve_company_framework(company).key == "auto_energy_optionality"


def test_general_rules_cover_industries_types_and_tags() -> None:
    for industry in ("Telecom", "Cable TV", "Fitness clubs", "Gym chain", "Leisure services"):
        assert resolve_company_framework(_company("ZZSUB", industry=industry)).key == "subscriber"
    assert resolve_company_framework(
        _company("ZZAE", company_type="auto_energy_growth")
    ).key == "auto_energy_optionality"
    assert resolve_company_framework(
        _company("ZZOP", tags=["optionality", "automobiles"])
    ).key == "auto_energy_optionality"
    assert resolve_company_framework(
        _company("ZZAI", company_type="ai_big_tech", tags=["ai"])
    ).key == "software_ai"


def test_basic_fit_is_a_subscriber_business_not_energy() -> None:
    basic_fit = _company(
        "BFIT.AS",
        company_type="research_candidate",
        industry="Fitness clubs",
        tags=["consumer", "fitness", "energy"],
    )
    assert resolve_company_framework(basic_fit).key == "subscriber"


def test_energy_alone_does_not_create_optionality_framework() -> None:
    utility = _company("ZZUTIL", company_type="energy_utility", industry="Utilities", tags=["energy"])
    assert resolve_company_framework(utility).key != "auto_energy_optionality"


def test_tsla_driver_model_runs_from_reported_revenue() -> None:
    framework = resolve_company_framework(
        _company(
            "TSLA",
            company_type="auto_energy_optionality",
            industry="Automobiles",
            tags=["auto", "ai", "energy", "optionality"],
        )
    )
    fact = SimpleNamespace(
        id=1,
        value=Decimal("1000"),
        unit="USD",
        fiscal_year=2025,
        fiscal_quarter="FY",
        period="FY2025",
    )
    result = DriverOperatingModel().build(
        framework,
        {"revenue": [fact]},
        latest_year=2025,
        horizon=1,
        scenario="base",
    )
    assert result["status"] != "missing_formula_inputs"
    assert result["status"] == "driver_based"
    assert result["output_metric"] == "revenue"
    assert result["years"][0]["output"] == pytest.approx(1000.0)


def test_asts_keeps_space_network_and_its_eight_inputs() -> None:
    framework = resolve_company_framework(
        _company(
            "ASTS",
            company_type="space_telecom_pre_fcf",
            industry="Satellite telecom",
            tags=["space", "speculative", "pre_fcf", "telecom"],
        )
    )
    assert framework.key == "space_network"
    assert FORMULAS["space_network"].inputs == (
        "addressable_subscribers",
        "penetration",
        "monthly_arpu",
        "revenue_share",
        "satellites",
        "capacity_per_satellite",
        "utilization",
        "price_per_gb",
    )
    assert len(FORMULAS["space_network"].inputs) == 8
