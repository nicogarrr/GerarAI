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



def _co_ind(ticker="X", company_type="research_candidate", model="unassigned", industry="Unknown", tags=None):
    return SimpleNamespace(ticker=ticker, valuation_model=model, factor_tags=tags or [],
                           company_type=company_type, industry=industry)


def test_engine_moves_only_verified_tickers():
    from app.services.company_framework import resolve_company_framework
    assert resolve_engine_key(_co_ind(ticker="CB")) == "insurer"
    assert resolve_engine_key(_co_ind(ticker="KKR")) == "holding_company"
    assert resolve_engine_key(_co_ind(ticker="CPT")) == "reit"
    assert resolve_engine_key(_co_ind(ticker="BN")) == "holding_company"
    assert resolve_company_framework(_co_ind(ticker="CB")).key == "insurer"
    assert resolve_company_framework(_co_ind(ticker="KKR")).key == "holding_asset_manager"
    assert resolve_company_framework(_co_ind(ticker="CPT")).key == "reit"


def test_engine_counterexamples_auditor():
    # AON/MMC: "Insurance Brokers" NO son aseguradoras (main ya lo excluía).
    assert resolve_engine_key(_co_ind(ticker="AON", industry="Insurance Brokers")) == "standard_dcf"
    assert resolve_engine_key(_co_ind(ticker="MMC", industry="Insurance Brokers")) == "standard_dcf"
    # CBRE/Zillow: "Real Estate Services/Development" NO son REITs.
    assert resolve_engine_key(_co_ind(ticker="CBRE", industry="Real Estate Services")) == "standard_dcf"
    assert resolve_engine_key(_co_ind(ticker="Z", industry="Real Estate - Development")) == "standard_dcf"
    # Bancos y gestoras por industria NO cambian de motor (siguen standard_dcf
    # hasta que su motor tenga datos suficientes).
    assert resolve_engine_key(_co_ind(ticker="XYZ", industry="Banks - Regional")) == "standard_dcf"
    assert resolve_engine_key(_co_ind(ticker="XYZ", industry="Asset Management")) == "standard_dcf"
    # La regla insurer por industria de main sigue viva para aseguradoras puras.
    assert resolve_engine_key(_co_ind(ticker="XYZ", industry="Insurance - Property & Casualty")) == "insurer"


def test_framework_industry_signal_and_counterexamples():
    from app.services.company_framework import resolve_company_framework
    assert resolve_company_framework(_co_ind(industry="Insurance - Property & Casualty")).key == "insurer"
    assert resolve_company_framework(_co_ind(industry="REIT - Residential")).key == "reit"
    assert resolve_company_framework(_co_ind(industry="Asset Management")).key == "holding_asset_manager"
    assert resolve_company_framework(_co_ind(industry="Banks - Regional")).key == "bank"
    # Contraejemplos: brokers e inmobiliarias de servicios no cambian de marco.
    assert resolve_company_framework(_co_ind(industry="Insurance Brokers")).key == "generic_fcf"
    assert resolve_company_framework(_co_ind(industry="Real Estate Services")).key == "generic_fcf"
    # Sin industria ni tipo, el marco genérico no cambia.
    assert resolve_company_framework(_co_ind()).key == "generic_fcf"
    assert resolve_engine_key(_co_ind()) == "standard_dcf"
    # company_type decidido manda sobre la industria.
    assert resolve_company_framework(_co_ind(company_type="biotech_pre_fcf", industry="Technology")).key == "biotech_pre_fcf"
