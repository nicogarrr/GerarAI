from types import SimpleNamespace

from app.valuation.engines import resolve_engine_key


def _co(**kw):
    base = dict(valuation_model="unassigned", factor_tags=[], company_type="research_candidate", industry="Unknown")
    base.update(kw)
    return SimpleNamespace(**base)


def test_insurance_industry_routes_to_insurer_when_company_type_is_generic():
    assert resolve_engine_key(_co(industry="Insurance")) == "insurer"
    assert resolve_engine_key(_co(industry="Insurance - Property & Casualty")) == "insurer"


def test_insurance_brokers_and_other_industries_keep_standard_dcf():
    assert resolve_engine_key(_co(industry="Insurance Brokers")) == "standard_dcf"
    assert resolve_engine_key(_co(industry="Software")) == "standard_dcf"
    assert resolve_engine_key(_co(industry="Financial Services")) == "standard_dcf"


def test_explicit_company_type_still_wins():
    assert resolve_engine_key(_co(company_type="bank", industry="Insurance")) == "bank"
