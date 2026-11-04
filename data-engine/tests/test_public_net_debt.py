from datetime import date
from decimal import Decimal

from app.valuation.public_inputs.net_debt import PublicFact, calculate_net_debt, parse_sec_balances

END = date(2026, 9, 30)
ASOF = date(2026, 11, 4)
URL = "https://www.sec.gov/Archives/edgar/data/1321655/000132165526000048/pltr-20260930.htm"


def fact(metric, value, unit="USD", end=END, filed=date(2026, 11, 3)):
    return PublicFact(metric, Decimal(str(value)), unit, end, filed, URL, metric)


def calc(rows):
    return calculate_net_debt(rows, period_end=END, as_of=ASOF, currency="USD")


def test_aggregate_debt_never_double_counts_components():
    rows = [fact("total_debt", 100), fact("short_term_debt", 10), fact("long_term_debt", 90),
            fact("cash_and_equivalents", 30), fact("short_term_investments", 20)]
    assert calc(rows)["net_debt"] == Decimal(50)
    assert len(calc(rows)["components"]) == 3


def test_missing_debt_is_not_zero_even_with_pltr_cash():
    result = calc([fact("cash_and_equivalents", 3619414000), fact("short_term_investments", 6942117000)])
    assert result["status"] == "missing"
    assert result["net_debt"] is None


def test_explicit_zero_debt_is_traceable_net_cash():
    result = calc([fact("total_debt", 0), fact("cash_and_equivalents", 30), fact("short_term_investments", 20)])
    assert result["net_debt"] == -50
    assert all(c["source_url"] == URL for c in result["components"])


def test_wrong_currency_date_and_future_are_not_combined():
    assert calc([fact("total_debt", 100, unit="EUR"), fact("cash_and_equivalents", 30)])["net_debt"] is None
    assert calc([fact("total_debt", 100, end=date(2025, 12, 31))])["net_debt"] is None
    assert calc([fact("total_debt", 100, filed=date(2027, 1, 1))])["net_debt"] is None


def test_complete_components_and_missing_investments():
    result = calc([fact("short_term_debt", 10), fact("long_term_debt", 20), fact("cash_and_equivalents", 5)])
    assert result["net_debt"] is None
    assert result["net_debt_ex_cash_only"] == 25


def test_conflicting_same_date_values_are_not_silently_chosen():
    assert calc([fact("total_debt", 100), fact("total_debt", 200)])["status"] == "conflict"


def test_sec_parser_preserves_instant_units_publication_and_refs():
    row = {"val": 3619414000, "end": "2026-09-30", "filed": "2026-11-03", "form": "10-Q", "accn": "0001321655-26-000048"}
    payload = {"facts": {"us-gaap": {"CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [row, {**row, "start": "2026-01-01"}]}}}}}
    rows = parse_sec_balances(payload, source_url=URL, as_of=ASOF)
    assert len(rows) == 1 and rows[0].value == 3619414000
    assert "0001321655-26-000048" in rows[0].fact_ref
    assert parse_sec_balances(payload, source_url=URL, as_of=date(2026, 10, 1)) == []
