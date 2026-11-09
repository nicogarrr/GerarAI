"""Fail-closed regression for nonfinite HTML values and unknown accessions in all same-filing derivations."""

import copy
from decimal import Decimal

import pytest

from app.services import filing_html_tables as tables
from app.services.financial_ingestion_service import (
    DERIVED_OPERATING_LEASE_TOTAL,
    SEC_METRIC_MAP,
    with_derived_operating_lease_total,
)


def annual_table(value):
    return (
        "<table><tr><td>For the years ended Dec. 31 (millions)</td></tr>"
        "<tr><td>2025</td></tr><tr><td>Distributable earnings</td><td>" + value + "</td></tr></table>"
    )


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", "(Infinity)"])
def test_html_nonfinite_cells_never_resolve_as_annual_values(value):
    assert tables.resolve(annual_table(value), ["distributable_earnings"], source="fixture") == {}
    assert tables._number(value) is None
    assert tables.read_annual_rows(annual_table(value)) == []


@pytest.mark.parametrize(
    "value,expected", [("0", Decimal(0)), ("(12)", Decimal(-12)), ("1.25", Decimal("1.25"))]
)
def test_html_finite_values_remain_supported(value, expected):
    found = tables.resolve(annual_table(value), ["distributable_earnings"], source="fixture")[
        "distributable_earnings"
    ]
    assert found.conflict is None
    assert found.values == {("2025-01-01", "2025-12-31"): expected * 1_000_000}


def lease_facts(noncurrent_accession, current_accession):
    def entry(value, accession):
        row = {"end": "2026-09-30", "val": value}
        if accession != "MISSING_KEY":
            row["accn"] = accession
        return row

    return {
        "OperatingLeaseLiabilityNoncurrent": {"units": {"USD": [entry(10, noncurrent_accession)]}},
        "OperatingLeaseLiabilityCurrent": {"units": {"USD": [entry(5, current_accession)]}},
    }


@pytest.mark.parametrize(
    "accession", ["MISSING_KEY", None, "", "  ", 0, False, "N/D", "unknown", "null", "-"]
)
def test_unknown_accessions_never_prove_same_filing(accession):
    facts = lease_facts(accession, accession)
    original = copy.deepcopy(facts)
    out, mapping = with_derived_operating_lease_total(facts, SEC_METRIC_MAP)
    assert DERIVED_OPERATING_LEASE_TOTAL not in out
    assert out is facts and mapping is SEC_METRIC_MAP
    assert facts == original


@pytest.mark.parametrize("nc,current", [(None, "known"), ("known", None), ("one", "two")])
def test_one_unknown_or_different_accession_does_not_sum(nc, current):
    out, _ = with_derived_operating_lease_total(lease_facts(nc, current), SEC_METRIC_MAP)
    assert DERIVED_OPERATING_LEASE_TOTAL not in out


def test_known_same_accession_still_sums_without_mutating_components():
    facts = lease_facts("known-accession", "known-accession")
    original = copy.deepcopy(facts)
    out, _ = with_derived_operating_lease_total(facts, SEC_METRIC_MAP)
    assert out[DERIVED_OPERATING_LEASE_TOTAL]["units"]["USD"][0]["val"] == 15
    assert (
        "mismo filing known-accession"
        in out[DERIVED_OPERATING_LEASE_TOTAL]["units"]["USD"][0]["_derived_from"]
    )
    assert facts == original


@pytest.mark.parametrize("kind", ["ifrs_da", "operating_income", "short_term_investments"])
@pytest.mark.parametrize(
    "accession", ["MISSING_KEY", None, "", "  ", 0, False, "N/D", "unknown", "null", "-"]
)
def test_other_derivations_require_known_accession(kind, accession):

    facts, function, mapping, synthetic = other_derivation(kind, accession)
    before = copy.deepcopy(facts)
    out, result_map = function(facts, mapping)
    assert synthetic not in out
    assert out is facts and result_map is mapping
    assert facts == before


def other_derivation(kind, accession):
    import app.services.financial_ingestion_service as ingestion

    def entry(value):
        row = {"start": "2025-01-01", "end": "2025-12-31", "val": value}
        if kind == "short_term_investments":
            row.pop("start")
        if accession != "MISSING_KEY":
            row["accn"] = accession
        return row

    if kind == "short_term_investments":
        values = {
            "CashCashEquivalentsAndShortTermInvestments": 100,
            "CashAndCashEquivalentsAtCarryingValue": 20,
        }
        function, mapping, synthetic = (
            ingestion.with_derived_short_term_investments,
            ingestion.SEC_METRIC_MAP,
            ingestion.DERIVED_SHORT_TERM_INVESTMENTS,
        )
    elif kind == "ifrs_da":
        values = {"DepreciationExpense": 10, "AmortisationExpense": 5}
        function, mapping, synthetic = (
            ingestion.with_derived_ifrs_depreciation_amortisation,
            ingestion.SEC_IFRS_METRIC_MAP,
            ingestion.DERIVED_IFRS_DA,
        )
    else:
        values = {
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 100,
            "NonoperatingIncomeExpense": 20,
            "RevenueFromContractWithCustomerIncludingAssessedTax": 150,
            "OperatingExpenses": 70,
        }
        function, mapping, synthetic = (
            ingestion.with_derived_operating_income,
            ingestion.SEC_METRIC_MAP,
            ingestion.DERIVED_OPERATING_INCOME,
        )
    return (
        {name: {"units": {"USD": [entry(value)]}} for name, value in values.items()},
        function,
        mapping,
        synthetic,
    )


@pytest.mark.parametrize(
    "kind,expected", [("ifrs_da", 15), ("operating_income", 80), ("short_term_investments", 80)]
)
def test_known_accession_derivations_still_work(kind, expected):
    facts, function, mapping, synthetic = other_derivation(kind, "known-accession")
    before = copy.deepcopy(facts)
    out, _ = function(facts, mapping)
    assert out[synthetic]["units"]["USD"][0]["val"] == expected
    assert facts == before


@pytest.mark.parametrize(
    "concept",
    ["NonoperatingIncomeExpense", "RevenueFromContractWithCustomerIncludingAssessedTax", "OperatingExpenses"],
)
def test_each_operating_component_requires_its_own_known_matching_accession(concept):
    facts, function, mapping, synthetic = other_derivation("operating_income", "known-accession")
    facts[concept]["units"]["USD"][0].pop("accn")
    assert synthetic not in function(facts, mapping)[0]


@pytest.mark.parametrize("kind", ["ifrs_da", "operating_income", "short_term_investments"])
def test_known_accessions_normalize_whitespace_but_do_not_mix_filings(kind):
    facts, function, mapping, synthetic = other_derivation(kind, "known-accession")
    first = next(iter(facts.values()))["units"]["USD"][0]
    first["accn"] = " known-accession "
    assert synthetic in function(facts, mapping)[0]
    first["accn"] = "different-accession"
    assert synthetic not in function(facts, mapping)[0]


def test_presented_operating_total_wins_even_without_accession():
    facts, function, mapping, synthetic = other_derivation("operating_income", "known-accession")
    facts["OperatingIncomeLoss"] = {
        "units": {"USD": [{"start": "2025-01-01", "end": "2025-12-31", "val": 70}]}
    }
    out, result_map = function(facts, mapping)
    assert synthetic not in out and result_map is mapping


@pytest.mark.parametrize("kind", ["ifrs_da", "short_term_investments"])
@pytest.mark.parametrize("which", [0, 1])
def test_each_pair_component_requires_known_accession(kind, which):
    facts, function, mapping, synthetic = other_derivation(kind, "known-accession")
    list(facts.values())[which]["units"]["USD"][0].pop("accn")
    assert synthetic not in function(facts, mapping)[0]


def test_lease_known_accessions_normalize_whitespace():
    facts = lease_facts(" known-accession ", "known-accession")
    out, _ = with_derived_operating_lease_total(facts, SEC_METRIC_MAP)
    assert out[DERIVED_OPERATING_LEASE_TOTAL]["units"]["USD"][0]["val"] == 15
