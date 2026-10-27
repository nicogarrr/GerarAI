"""F410: owner earnings must read the canonical D&A key written by ingestion."""
from types import SimpleNamespace

from app.services.long_term_model_service import LongTermModelService


def _fact(value):
    return SimpleNamespace(value=value, id="f", period="FY2024")


def _service():
    svc = LongTermModelService.__new__(LongTermModelService)
    svc._annual_by_year = lambda facts: {2024: facts[0]} if facts else {}
    return svc


def _cache(**overrides):
    base = {
        "net_income": [_fact(100)],
        "maintenance_capex": [_fact(10)],
        "capital_expenditure": [],
        # Signo de flujo de caja: −5 = el circulante absorbió 5 de caja.
        "change_in_working_capital": [_fact(-5)],
        "depreciation_amortization": [],
        "depreciation_and_amortization": [],
    }
    base.update(overrides)
    return base


def test_owner_earnings_uses_canonical_key_written_by_ingestion():
    result = _service()._owner_earnings(_cache(depreciation_amortization=[_fact(20)]), 2024)
    assert result["status"] == "ok"
    assert result["value"] == 100 + 20 - 10 - 5


def test_owner_earnings_falls_back_to_legacy_key():
    result = _service()._owner_earnings(_cache(depreciation_and_amortization=[_fact(20)]), 2024)
    assert result["status"] == "ok"


def test_owner_earnings_without_da_stays_insufficient():
    result = _service()._owner_earnings(_cache(), 2024)
    assert result["status"] == "insufficient_data"
