"""total_debt: explicit definition, one tag per component, no double counting."""

import pytest

from app.services.financial_ingestion_service import (
    SEC_METRIC_MAP,
    _collect_by_concept,
    _merge_for_metric,
)

END = "2024-12-31"


def _fact(val, filed="2025-02-01"):
    return {
        "end": END, "val": val, "filed": filed, "form": "10-K", "fp": "FY",
        "accn": "0000000000-25-000001",
    }


def _debt(**tags):
    us_gaap = {k: {"units": {"USD": [_fact(v)]}} for k, v in tags.items()}
    concepts = next(c for m, c, _ in SEC_METRIC_MAP if m == "total_debt")
    merged = _merge_for_metric(
        _collect_by_concept(
            us_gaap, concepts, "USD", forms={"10-K"}, periods={"FY"},
            min_span=None, max_span=None,
        ),
        "total_debt",
    )
    return merged.get(END)


def test_declared_total_wins_alone():
    row = _debt(
        DebtLongtermAndShorttermCombinedAmount=900, LongTermDebt=700,
        ShortTermBorrowings=50, FinanceLeaseLiability=30,
    )
    assert row["val"] == 900
    assert row["_concept"] == "DebtLongtermAndShorttermCombinedAmount"


def test_long_term_debt_plus_short_borrowings_plus_leases():
    row = _debt(LongTermDebt=700, ShortTermBorrowings=50, FinanceLeaseLiability=30)
    assert row["val"] == 780
    assert row["_components"].keys() == {"LongTermDebt", "ShortTermBorrowings", "FinanceLeaseLiability"}


def test_noncurrent_adds_current_portion():
    row = _debt(LongTermDebtNoncurrent=600, LongTermDebtCurrent=100)
    assert row["val"] == 700


def test_current_portion_not_added_to_long_term_debt_which_includes_it():
    row = _debt(LongTermDebt=700, LongTermDebtCurrent=100)
    assert row["val"] == 700


def test_capital_lease_tag_already_includes_leases_no_double_count():
    row = _debt(LongTermDebtAndCapitalLeaseObligations=800, FinanceLeaseLiability=100)
    assert row["val"] == 800
    assert "FinanceLeaseLiability" not in row["_components"]


def test_breakdown_tags_not_added_on_top_of_term_debt():
    row = _debt(LongTermDebt=700, NotesPayable=200, ConvertibleDebt=100, LongTermLineOfCredit=50)
    assert row["val"] == 700


def test_loose_components_sum_one_tag_per_component():
    row = _debt(
        ConvertibleDebt=100, ConvertibleNotesPayable=999, NotesPayable=40,
        LongTermNotesPayable=777, LinesOfCreditCurrent=10, FinanceLeaseLiability=5,
    )
    assert row["val"] == 155
    assert "ConvertibleNotesPayable" not in row["_components"]
    assert "LongTermNotesPayable" not in row["_components"]


def test_instrument_carrying_amount_is_last_resort_only():
    assert _debt(DebtInstrumentCarryingAmount=300)["val"] == 300
    assert _debt(NotesPayable=40, DebtInstrumentCarryingAmount=300)["val"] == 40


def test_no_debt_tag_means_no_value_not_zero():
    assert _debt(Assets=1000) is None


def test_zero_reported_is_kept_as_zero():
    assert _debt(LongTermDebt=0)["val"] == 0


def test_short_borrowings_single_tag():
    row = _debt(LongTermDebt=500, ShortTermBorrowings=20, LinesOfCreditCurrent=999)
    assert row["val"] == 520


@pytest.mark.parametrize("tags", [dict(LongTermDebt=1)])
def test_provenance_lists_every_component(tags):
    assert _debt(**tags)["_concept"] == "LongTermDebt"


def test_lone_finance_lease_is_not_total_debt():
    assert _debt(FinanceLeaseLiability=890) is None


def test_lone_finance_lease_falls_to_instrument_amount_if_present():
    assert _debt(FinanceLeaseLiability=890, DebtInstrumentCarryingAmount=300)["val"] == 300


def test_apple_commercial_paper_is_counted():
    """Apple FY2025: LongTermDebt 90,678 + CP 7,979 + finance leases 1,230."""
    row = _debt(LongTermDebt=90_678, CommercialPaper=7_979, FinanceLeaseLiability=1_230)
    assert row["val"] == 99_887
    assert row["_components"].keys() == {"LongTermDebt", "CommercialPaper", "FinanceLeaseLiability"}


def test_short_debt_one_tag_priority():
    row = _debt(LongTermDebt=100, ShortTermBorrowings=5, CommercialPaper=7, LinesOfCreditCurrent=9)
    assert row["val"] == 105
    row = _debt(LongTermDebt=100, CommercialPaper=7, LinesOfCreditCurrent=9)
    assert row["val"] == 107
