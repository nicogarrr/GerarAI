"""Resultado operativo US GAAP sin OperatingIncomeLoss (regla 21 de ingesta SEC), con cuadre de dos caminos.

ASTS (10-K 2025, real) no etiqueta «Loss from operations» desde 2021: antes de impuestos −457,113 M$ y no
operativo −169,4 M$ dan −287,713 M$, igual que ingresos 70,918 − gastos operativos 358,631. Muestra de 1.500
emisores de companyfacts (9-nov-2026) con OperatingIncomeLoss oculto: la regla coincide con el presentado en
13.561 de 13.599 periodos (99,7 %).
"""
from __future__ import annotations

from app.services.financial_ingestion_service import (
    DERIVED_OPERATING_INCOME,
    SEC_IFRS_METRIC_MAP,
    SEC_INGESTION_RULES_VERSION,
    SEC_METRIC_MAP,
    _synthetic,
    with_derived_operating_income,
)

ASTS_10K = "0001780312-26-000006"
FY = ("2025-01-01", "2025-12-31")


def _e(val, accn=ASTS_10K, period=FY):
    return {"start": period[0], "end": period[1], "val": val, "accn": accn, "form": "10-K", "fp": "FY",
            "fy": 2025, "filed": "2026-03-02"}


def _facts(**concepts):
    return {name: {"units": {"USD": entries}} for name, entries in concepts.items()}


def _asts(**over):
    base = {
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": [_e(-457_113_000)],
        "NonoperatingIncomeExpense": [_e(-169_400_000)],
        "RevenueFromContractWithCustomerIncludingAssessedTax": [_e(70_918_000)],
        "OperatingExpenses": [_e(358_631_000)],
    }
    base.update(over)
    return _facts(**{k: v for k, v in base.items() if v is not None})


def test_asts_operating_loss_from_pretax_less_nonoperating():
    facts = _asts()
    out, mmap = with_derived_operating_income(facts, SEC_METRIC_MAP)
    got = out[DERIVED_OPERATING_INCOME]["units"]["USD"]
    assert [(e["end"], e["val"]) for e in got] == [("2025-12-31", -287_713_000.0)]
    assert "mismo filing" in got[0]["_derived_from"]
    cs = {m: c for m, c, _u in mmap}["operating_income"]
    assert cs[0] == "OperatingIncomeLoss" and cs[-1] == DERIVED_OPERATING_INCOME
    assert DERIVED_OPERATING_INCOME not in facts and _synthetic({"_concept": DERIVED_OPERATING_INCOME})
    assert SEC_INGESTION_RULES_VERSION >= 21


def test_no_cross_check_no_derivation():
    # Sin gastos operativos, o si los dos caminos no cuadran (el no operativo no es todo lo que separa), N/D.
    assert DERIVED_OPERATING_INCOME not in with_derived_operating_income(_asts(OperatingExpenses=None), SEC_METRIC_MAP)[0]
    off = _asts(OperatingExpenses=[_e(300_000_000)])
    assert DERIVED_OPERATING_INCOME not in with_derived_operating_income(off, SEC_METRIC_MAP)[0]


def test_gross_profit_path_also_counts():
    facts = _asts(RevenueFromContractWithCustomerIncludingAssessedTax=None, GrossProfit=[_e(70_918_000)])
    out, _ = with_derived_operating_income(facts, SEC_METRIC_MAP)
    assert out[DERIVED_OPERATING_INCOME]["units"]["USD"][0]["val"] == -287_713_000.0


def test_presented_operating_income_other_filing_and_ifrs_map_left_alone():
    presented = _asts(OperatingIncomeLoss=[_e(-287_713_000)])
    assert DERIVED_OPERATING_INCOME not in with_derived_operating_income(presented, SEC_METRIC_MAP)[0]
    mixed = _asts(NonoperatingIncomeExpense=[_e(-169_400_000, accn="0001780312-25-000001")])
    assert DERIVED_OPERATING_INCOME not in with_derived_operating_income(mixed, SEC_METRIC_MAP)[0]
    facts = _asts()
    out, mmap = with_derived_operating_income(facts, SEC_IFRS_METRIC_MAP)
    assert out is facts and mmap is SEC_IFRS_METRIC_MAP
