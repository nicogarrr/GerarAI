"""Ingresos de arrendadores: el arrendamiento (ASC 842) es el ingreso de un REIT.

Antes (main 95a9c193d): Camden (CPT) solo etiqueta como «revenue from contracts
with customers» una partida residual (12,97 M en 2025) y su ingreso real como
OperatingLeaseLeaseIncome (1.573,5 M); la ingesta guardaba 12,97 M de ingresos.
Ahora, en la misma presentación, gana el mayor de los dos (como ya hace la TIR).
"""

from app.services.financial_ingestion_service import (
    SEC_INGESTION_RULES_VERSION,
    SEC_METRIC_MAP,
    _merge_for_metric,
    _revenue_concepts_for,
)


def _entry(val, *, end="2025-12-31", accn="0000906345-26-000010", filed="2026-02-12"):
    return {"val": val, "end": end, "accn": accn, "filed": filed, "form": "10-K"}


def test_lessor_concepts_are_revenue_candidates():
    concepts = _revenue_concepts_for(next(c for m, c, _ in SEC_METRIC_MAP if m == "revenue"), bank_like=False)
    assert "OperatingLeaseLeaseIncome" in concepts
    assert SEC_INGESTION_RULES_VERSION >= 9


def test_cpt_lease_income_beats_residual_contract_revenue():
    by_concept = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"2025-12-31": _entry(12_967_000)},
        "OperatingLeaseLeaseIncome": {"2025-12-31": _entry(1_573_544_000)},
    }
    out = _merge_for_metric(by_concept, "revenue")
    assert out["2025-12-31"]["val"] == 1_573_544_000


def test_total_revenues_tag_still_wins_when_larger():
    by_concept = {
        "Revenues": {"2025-12-31": _entry(1_600_000_000)},
        "OperatingLeaseLeaseIncome": {"2025-12-31": _entry(1_573_544_000)},
    }
    assert _merge_for_metric(by_concept, "revenue")["2025-12-31"]["val"] == 1_600_000_000


def test_lease_income_from_another_filing_does_not_override():
    by_concept = {
        "Revenues": {"2025-12-31": _entry(100, accn="A")},
        "OperatingLeaseLeaseIncome": {"2025-12-31": _entry(900, accn="B", filed="2026-03-01")},
    }
    assert _merge_for_metric(by_concept, "revenue")["2025-12-31"]["val"] == 100


def test_lessor_only_filer_gets_revenue():
    by_concept = {"OperatingLeaseLeaseIncome": {"2024-12-31": _entry(42, end="2024-12-31")}}
    assert _merge_for_metric(by_concept, "revenue")["2024-12-31"]["val"] == 42
