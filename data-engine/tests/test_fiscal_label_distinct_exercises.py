"""Distinct fiscal closings, not amended filings, confirm a naming convention."""

from datetime import date

import pytest

from app.services.fiscal_label import dei_label_offset, filing_offsets


def annual(end_year, offset, accession, form="10-K"):
    return {
        "start": f"{end_year - 1}-02-01",
        "end": f"{end_year}-01-31",
        "filed": f"{end_year}-03-15",
        "fy": end_year - offset,
        "fp": "FY",
        "form": form,
        "accn": accession,
        "val": 100,
    }


def facts(*entries):
    return {"Revenues": {"units": {"USD": list(entries)}}}


@pytest.mark.parametrize("form,amendment", [("10-K", "10-K/A"), ("20-F", "20-F/A"), ("40-F", "40-F/A")])
def test_one_exercise_and_amendment_cannot_confirm_two_exercises(form, amendment):
    entries = [annual(2026, 1, "original", form), annual(2026, 1, "amendment", amendment)]
    assert len(filing_offsets(facts(*entries))) == 2  # preserve per-filing diagnostics
    assert dei_label_offset(facts(*entries)) == 0


def test_many_amendments_never_replace_second_exercise():
    assert dei_label_offset(facts(*(annual(2026, 1, str(i), "10-K/A") for i in range(20)))) == 0


def test_two_distinct_exercises_confirm_even_with_amendments():
    assert (
        dei_label_offset(
            facts(annual(2026, 1, "new"), annual(2026, 1, "amended", "10-K/A"), annual(2025, 1, "older"))
        )
        == 1
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_latest_amendments_do_not_hide_older_disagreement(reverse):
    entries = [annual(2026, 1, "z"), annual(2026, 1, "a", "10-K/A"), annual(2025, 0, "old")]
    assert dei_label_offset(facts(*reversed(entries) if reverse else entries)) == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_filings_for_one_closing_are_not_confirmation(reverse):
    entries = [annual(2026, 1, "z"), annual(2026, 0, "a", "10-K/A"), annual(2025, 1, "old")]
    assert dei_label_offset(facts(*reversed(entries) if reverse else entries)) == 0


def test_older_history_does_not_override_latest_two_exercises():
    entries = [annual(2026, 1, "new"), annual(2025, 1, "previous"), annual(2024, 0, "old")]
    assert dei_label_offset(facts(*entries)) == 1


def test_comparatives_are_still_not_separate_exercise_votes():
    comparison = annual(2025, 0, "new")
    comparison["filed"] = "2026-03-15"
    assert dei_label_offset(facts(annual(2026, 1, "new"), comparison)) == 0
    assert filing_offsets(facts(annual(2026, 1, "new"), comparison))[0][0] == date(2026, 1, 31)
