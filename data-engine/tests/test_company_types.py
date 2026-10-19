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
