"""Inversiones a corto derivadas del total combinado caja + inversiones menos la caja (regla 15 de ingesta SEC)."""
from __future__ import annotations

from app.services.financial_ingestion_service import (
    DERIVED_SHORT_TERM_INVESTMENTS,
    SEC_METRIC_MAP,
    with_derived_short_term_investments,
)


def _e(end, val, accn="0001703057-26-000046", form="10-Q", fp="Q2", filed="2026-08-05"):
    return {"end": end, "val": val, "accn": accn, "form": form, "fp": fp, "fy": 2026, "filed": filed}


def _facts(**concepts):
    return {name: {"units": {"USD": entries}} for name, entries in concepts.items()}


def test_abcl_shape_derives_marketable_securities():
    # ABCL 2T-2026 (10-Q real): caja 120.065 k$, subtotal caja + inversiones 540.104 k$, valores con
    # AvailableForSaleSecuritiesDebtSecurities (sin «Current»): las inversiones a corto no tenían concepto.
    facts = _facts(CashAndCashEquivalentsAtCarryingValue=[_e("2026-06-30", 120_065_000)],
                   CashCashEquivalentsAndShortTermInvestments=[_e("2026-06-30", 540_104_000)])
    out, mmap = with_derived_short_term_investments(facts, SEC_METRIC_MAP)
    got = out[DERIVED_SHORT_TERM_INVESTMENTS]["units"]["USD"]
    assert [(e["end"], e["val"]) for e in got] == [("2026-06-30", 420_039_000.0)]
    assert "mismo filing" in got[0]["_derived_from"]
    concepts = {m: cs for m, cs, _u in mmap}["short_term_investments"]
    assert concepts[-1] == DERIVED_SHORT_TERM_INVESTMENTS  # el concepto explícito siempre va antes
    assert DERIVED_SHORT_TERM_INVESTMENTS not in facts  # puro: no toca el payload de entrada


def test_explicit_concept_wins_and_other_filing_does_not_mix():
    facts = _facts(CashAndCashEquivalentsAtCarryingValue=[_e("2026-06-30", 100), _e("2025-12-31", 50, accn="A")],
                   CashCashEquivalentsAndShortTermInvestments=[_e("2026-06-30", 300), _e("2025-12-31", 90, accn="B")],
                   MarketableSecuritiesCurrent=[_e("2026-06-30", 200)])
    out, mmap = with_derived_short_term_investments(facts, SEC_METRIC_MAP)
    # 2026-06-30 tiene concepto explícito; 2025-12-31 mezcla dos filings distintos: nada derivado.
    assert DERIVED_SHORT_TERM_INVESTMENTS not in out
    assert mmap is SEC_METRIC_MAP


def test_no_positive_difference_no_fact():
    facts = _facts(CashAndCashEquivalentsAtCarryingValue=[_e("2026-06-30", 100)],
                   CashCashEquivalentsAndShortTermInvestments=[_e("2026-06-30", 100)])
    out, _ = with_derived_short_term_investments(facts, SEC_METRIC_MAP)
    assert DERIVED_SHORT_TERM_INVESTMENTS not in out
