"""Unknown ledger withholding must not turn into a made-up zero."""
from unittest.mock import Mock

import pytest

from app.services.brain_data_tools import _ledger_dividends_line
from app.services.tax_report_service import TaxReportService


@pytest.mark.parametrize("english", [False, True])
@pytest.mark.parametrize("withheld", [None, 0, 12.5])
def test_ledger_withholding_preserves_unknown_and_explicit_zero(monkeypatch, english, withheld):
    monkeypatch.setattr(TaxReportService, "compute_report", lambda *args, **kwargs: {
        "summary": {"total_dividends_base": 100, "total_withholding_base": withheld}
    })
    answer = _ledger_dividends_line(Mock(), 2026, english)
    assert answer is not None
    assert ("100.00 EUR" if english else "100,00 EUR") in answer
    if withheld is None:
        assert ("N/A withheld" if english else "N/D de retención") in answer
        assert "0.00 EUR withheld" not in answer and "0,00 EUR de retención" not in answer
    else:
        expected = ("0.00 EUR" if withheld == 0 else "12.50 EUR") if english else (
            "0,00 EUR" if withheld == 0 else "12,50 EUR"
        )
        assert expected in answer
        assert "N/A" not in answer and "N/D" not in answer


@pytest.mark.parametrize("english", [False, True])
def test_ledger_missing_withholding_key_is_unknown(monkeypatch, english):
    monkeypatch.setattr(TaxReportService, "compute_report", lambda *args, **kwargs: {
        "summary": {"total_dividends_base": 100}
    })
    answer = _ledger_dividends_line(Mock(), 2026, english)
    assert ("N/A withheld" if english else "N/D de retención") in answer
