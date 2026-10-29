"""Price lookup failures are not indistinguishable from absent prices."""
import logging

from app.services import valuation_service
from tests.test_valuation_honesty_contracts import company, db  # noqa: F401


def test_lookup_error_logs_class_without_secret_and_keeps_missing_price(db, company, monkeypatch, caplog):
    def fail(*args):
        raise RuntimeError("password=never-serialize-secret private SQL")
    monkeypatch.setattr(valuation_service, "resolve_model_price", fail)
    with caplog.at_level(logging.WARNING, logger=valuation_service.__name__):
        result = valuation_service.ValuationService().value_company(db, company)
    assert result["trace"]["price_status"] == "missing_market_price"
    assert result["trace"]["price_error"] == "RuntimeError"
    assert result.get("margin_of_safety") is None
    assert "RuntimeError" in caplog.text
    assert "never-serialize-secret" not in str(result) + caplog.text
    assert "private SQL" not in str(result) + caplog.text


def test_absent_price_is_not_marked_as_lookup_error(db, company, monkeypatch):
    monkeypatch.setattr(valuation_service, "resolve_model_price", lambda *args: None)
    result = valuation_service.ValuationService().value_company(db, company)
    assert result["trace"]["price_status"] == "missing_market_price"
    assert "price_error" not in result["trace"]
