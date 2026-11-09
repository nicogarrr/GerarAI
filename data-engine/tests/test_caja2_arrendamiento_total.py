"""Arrendamiento operativo total = no corriente + corriente del mismo filing (regla 17 de ingesta SEC)."""
from __future__ import annotations

from app.services.financial_ingestion_service import (
    DERIVED_OPERATING_LEASE_TOTAL,
    SEC_INGESTION_RULES_VERSION,
    SEC_METRIC_MAP,
    _synthetic,
    with_derived_operating_lease_total,
)

META_Q3 = "0001628280-26-066773"


def _e(end, val, accn=META_Q3, form="10-Q", fp="Q3", filed="2026-10-22"):
    return {"end": end, "val": val, "accn": accn, "form": form, "fp": fp, "fy": 2026, "filed": filed}


def _facts(**concepts):
    return {name: {"units": {"USD": entries}} for name, entries in concepts.items()}


def _lease_concepts(mmap):
    return {m: cs for m, cs, _u in mmap}["operating_lease_liabilities"]


def test_meta_q3_balance_lines_sum_to_total():
    # META 10-Q 3T 2026 (real): balance con no corriente 28.651 M$ y corriente 2.522 M$, sin el total etiquetado.
    facts = _facts(OperatingLeaseLiabilityNoncurrent=[_e("2026-09-30", 28_651_000_000)],
                   OperatingLeaseLiabilityCurrent=[_e("2026-09-30", 2_522_000_000)],
                   OperatingLeaseLiability=[_e("2025-12-31", 25_153_000_000, accn="0001628280-26-003942", form="10-K", fp="FY")])
    out, mmap = with_derived_operating_lease_total(facts, SEC_METRIC_MAP)
    got = out[DERIVED_OPERATING_LEASE_TOTAL]["units"]["USD"]
    assert [(e["end"], e["val"]) for e in got] == [("2026-09-30", 31_173_000_000.0)]
    assert "mismo filing" in got[0]["_derived_from"]
    cs = _lease_concepts(mmap)
    # el total presentado gana; la suma va antes que la no corriente sola
    assert cs.index("OperatingLeaseLiability") < cs.index(DERIVED_OPERATING_LEASE_TOTAL) < cs.index(
        "OperatingLeaseLiabilityNoncurrent")
    assert DERIVED_OPERATING_LEASE_TOTAL not in facts  # puro
    assert _synthetic({"_concept": DERIVED_OPERATING_LEASE_TOTAL})  # se guarda como no reportado tal cual


def test_explicit_total_wins_and_other_filing_does_not_mix():
    facts = _facts(OperatingLeaseLiabilityNoncurrent=[_e("2026-09-30", 100), _e("2026-06-30", 90, accn="A")],
                   OperatingLeaseLiabilityCurrent=[_e("2026-09-30", 10), _e("2026-06-30", 9, accn="B")],
                   OperatingLeaseLiability=[_e("2026-09-30", 110)])
    out, mmap = with_derived_operating_lease_total(facts, SEC_METRIC_MAP)
    # 2026-09-30 ya tiene total; 2026-06-30 mezcla dos filings: nada derivado.
    assert DERIVED_OPERATING_LEASE_TOTAL not in out
    assert mmap is SEC_METRIC_MAP


def test_without_current_part_nothing_is_derived():
    # PINS: solo la no corriente en el balance (la corriente va dentro de otros pasivos): queda como estaba.
    facts = _facts(OperatingLeaseLiabilityNoncurrent=[_e("2026-09-30", 214_242_000)],
                   OperatingLeaseLiabilityCurrent=[_e("2025-12-31", 40_000_000, accn="10K")])
    out, mmap = with_derived_operating_lease_total(facts, SEC_METRIC_MAP)
    assert DERIVED_OPERATING_LEASE_TOTAL not in out
    assert mmap is SEC_METRIC_MAP


def test_negative_or_duration_facts_are_ignored():
    facts = _facts(OperatingLeaseLiabilityNoncurrent=[_e("2026-09-30", -5), {**_e("2026-09-30", 7), "start": "2026-07-01"}],
                   OperatingLeaseLiabilityCurrent=[_e("2026-09-30", 3)])
    out, _ = with_derived_operating_lease_total(facts, SEC_METRIC_MAP)
    assert DERIVED_OPERATING_LEASE_TOTAL not in out


def test_rules_version_bumped():
    assert SEC_INGESTION_RULES_VERSION >= 17
