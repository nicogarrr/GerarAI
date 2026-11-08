"""Deuda total con la parte corriente cuando solo se etiqueta su total (DebtCurrent).

Antes: UNH (10-Q 3T 2026) etiqueta LongTermDebtNoncurrent 68.714 M y DebtCurrent
5.617 M, sin LongTermDebtCurrent; total_debt salía 68.714 M (faltaba la corriente).
"""

from app.services.financial_ingestion_service import (
    SEC_INGESTION_RULES_VERSION,
    TOTAL_DEBT_CONCEPTS,
    _merge_for_metric,
)

END = "2026-09-30"


def _e(val, accn="0000731766-26-000050"):
    return {END: {"val": val, "end": END, "accn": accn, "filed": "2026-11-04", "form": "10-Q"}}


def test_unh_noncurrent_plus_current_total():
    assert "DebtCurrent" in TOTAL_DEBT_CONCEPTS
    assert SEC_INGESTION_RULES_VERSION >= 10
    out = _merge_for_metric({"LongTermDebtNoncurrent": _e(68_714), "DebtCurrent": _e(5_617)}, "total_debt")
    assert out[END]["val"] == 74_331
    assert out[END]["_components"] == {"LongTermDebtNoncurrent": "68714", "DebtCurrent": "5617"}


def test_debt_current_replaces_short_borrowings_not_added():
    out = _merge_for_metric(
        {"LongTermDebtNoncurrent": _e(100), "DebtCurrent": _e(30), "CommercialPaper": _e(20)}, "total_debt"
    )
    assert out[END]["val"] == 130


def test_explicit_current_maturity_keeps_previous_rule():
    out = _merge_for_metric(
        {"LongTermDebtNoncurrent": _e(100), "LongTermDebtCurrent": _e(10), "DebtCurrent": _e(30),
         "CommercialPaper": _e(20)},
        "total_debt",
    )
    assert out[END]["val"] == 130  # 100 + 10 + papel 20; DebtCurrent no se suma encima


def test_long_term_debt_including_current_is_untouched():
    out = _merge_for_metric({"LongTermDebt": _e(100), "DebtCurrent": _e(30)}, "total_debt")
    assert out[END]["val"] == 100
