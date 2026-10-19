from types import SimpleNamespace

from app.services.company_types import is_holding_company_type
from app.valuation.engines.registry import resolve_engine_key


def test_position_types_are_not_holding_companies():
    assert not is_holding_company_type("portfolio_holding")
    assert not is_holding_company_type("imported_holding")
    assert is_holding_company_type("asset_manager_holding")
    assert is_holding_company_type("china_adr_holding")
    assert not is_holding_company_type(None)


def test_engine_key_for_portfolio_position_is_not_holding():
    co = SimpleNamespace(valuation_model="unassigned", factor_tags=[], company_type="portfolio_holding")
    assert resolve_engine_key(co) != "holding_company"
    co2 = SimpleNamespace(valuation_model="unassigned", factor_tags=[], company_type="asset_manager_holding")
    assert resolve_engine_key(co2) == "holding_company"


def _co(ticker="X", company_type="research_candidate", model="unassigned", industry="Unknown", tags=None):
    return SimpleNamespace(ticker=ticker, valuation_model=model, factor_tags=tags or [],
                           company_type=company_type, industry=industry)


def test_engine_and_framework_use_industry_when_type_is_generic():
    from app.services.company_framework import resolve_company_framework
    assert resolve_engine_key(_co(industry="Insurance")) == "insurer"
    assert resolve_engine_key(_co(industry="Real Estate")) == "reit"
    assert resolve_engine_key(_co(industry="REIT")) == "reit"
    assert resolve_engine_key(_co(industry="Asset Management")) == "holding_company"
    assert resolve_engine_key(_co(industry="Banking")) == "bank"
    assert resolve_company_framework(_co(industry="Insurance")).key == "insurer"
    assert resolve_company_framework(_co(industry="Real Estate")).key == "reit"
    assert resolve_company_framework(_co(industry="Asset Management")).key == "holding_asset_manager"


def test_explicit_verified_tickers_cb_kkr_cpt():
    from app.services.company_framework import resolve_company_framework
    assert resolve_company_framework(_co(ticker="CB")).key == "insurer"
    assert resolve_company_framework(_co(ticker="KKR")).key == "holding_asset_manager"
    assert resolve_company_framework(_co(ticker="CPT")).key == "reit"
    # Sin industria ni tipo, el generico sigue siendo el FCF estandar.
    assert resolve_company_framework(_co()).key == "generic_fcf"
    assert resolve_engine_key(_co()) == "standard_dcf"


def test_company_type_specific_wins_over_industry():
    from app.services.company_framework import resolve_company_framework
    # company_type decidido manda sobre una industria generica.
    assert resolve_company_framework(_co(company_type="biotech_pre_fcf", industry="Technology")).key == "biotech_pre_fcf"
    assert resolve_engine_key(_co(company_type="bank", industry="Technology")) == "bank"
    assert resolve_engine_key(_co(company_type="biotech_pre_fcf", tags=["pre_fcf"], industry="Technology")) == "pre_revenue"
