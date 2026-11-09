"""EBITDA de emisores IFRS (9-nov-2026): amortizaciones TSM (regla 20 de ingesta SEC) y EBITDA por componentes en el Informe.

Antes, en el Informe el EBITDA salía «—» en CNQ (40-F) y Airbus (ESEF), que no etiquetan resultado operativo,
y en TSM (20-F), que no etiqueta el total de amortizaciones sino depreciación y amortización por separado.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.analyst_report import FactRow, build_estimates, interest_is_operating
from app.services.financial_ingestion_service import (
    DERIVED_IFRS_DA,
    SEC_IFRS_METRIC_MAP,
    SEC_INGESTION_RULES_VERSION,
    SEC_METRIC_MAP,
    _synthetic,
    with_derived_ifrs_depreciation_amortisation,
)

TSM_20F = "0001628280-26-025362"


def _e(start, end, val, accn=TSM_20F):
    return {"start": start, "end": end, "val": val, "accn": accn, "form": "20-F", "fp": "FY", "fy": 2025,
            "filed": "2026-04-15"}


def _facts(**concepts):
    return {name: {"units": {"TWD": entries}} for name, entries in concepts.items()}


def _da_concepts(mmap):
    return {m: cs for m, cs, _u in mmap}["depreciation_amortization"]


def test_tsm_depreciation_plus_amortisation_same_filing():
    # TSM 20-F (real): depreciación 653.610,5 + amortización 9.186,1 M TWD en 2024, sin el total etiquetado.
    facts = _facts(DepreciationExpense=[_e("2024-01-01", "2024-12-31", 653_610_500_000)],
                   AmortisationExpense=[_e("2024-01-01", "2024-12-31", 9_186_100_000)])
    out, mmap = with_derived_ifrs_depreciation_amortisation(facts, SEC_IFRS_METRIC_MAP)
    got = out[DERIVED_IFRS_DA]["units"]["TWD"]
    assert [(e["end"], e["val"]) for e in got] == [("2024-12-31", 662_796_600_000.0)]
    assert "mismo filing" in got[0]["_derived_from"]
    cs = _da_concepts(mmap)
    # los totales presentados (cuenta de resultados y estado de flujos) ganan; la suma va la última
    assert cs == ["DepreciationAndAmortisationExpense", "AdjustmentsForDepreciationAndAmortisationExpense", DERIVED_IFRS_DA]
    assert DERIVED_IFRS_DA not in facts  # puro
    assert _synthetic({"_concept": DERIVED_IFRS_DA})
    assert SEC_INGESTION_RULES_VERSION >= 20


def test_presented_total_wins_other_filing_and_missing_part_do_not_mix():
    facts = _facts(
        DepreciationExpense=[_e("2024-01-01", "2024-12-31", 100), _e("2023-01-01", "2023-12-31", 90, accn="A"),
                             _e("2022-01-01", "2022-12-31", 80)],
        AmortisationExpense=[_e("2024-01-01", "2024-12-31", 10), _e("2023-01-01", "2023-12-31", 9, accn="B")],
        AdjustmentsForDepreciationAndAmortisationExpense=[_e("2024-01-01", "2024-12-31", 111)],
    )
    out, _mmap = with_derived_ifrs_depreciation_amortisation(facts, SEC_IFRS_METRIC_MAP)
    # 2024 ya tiene total; 2023 mezcla dos filings; 2022 no tiene amortización: nada derivado.
    assert DERIVED_IFRS_DA not in out


def test_negative_part_or_us_gaap_map_leave_everything_as_is():
    facts = _facts(DepreciationExpense=[_e("2024-01-01", "2024-12-31", 100)],
                   AmortisationExpense=[_e("2024-01-01", "2024-12-31", -5)])
    assert DERIVED_IFRS_DA not in with_derived_ifrs_depreciation_amortisation(facts, SEC_IFRS_METRIC_MAP)[0]
    ok = _facts(DepreciationExpense=[_e("2024-01-01", "2024-12-31", 100)],
                AmortisationExpense=[_e("2024-01-01", "2024-12-31", 5)])
    out, mmap = with_derived_ifrs_depreciation_amortisation(ok, SEC_METRIC_MAP)  # mapa us-gaap: no aplica
    assert out is ok and mmap is SEC_METRIC_MAP


# --- Informe: EBITDA por componentes -----------------------------------------------------------------

END = date(2025, 12, 31)


def _row(metric, value, *, unit="CAD", end=END, quarter="FY"):
    return FactRow(metric=metric, kind="FY" if quarter == "FY" else "Q", quarter=quarter, end=end,
                   value=Decimal(str(value)), unit=unit, reported=True, source="SEC", rank=(10.0, 0.0),
                   url="https://www.sec.gov/Archives/edgar/data/1017413/000101741326000018/")


def _cnq_2025(**over):
    # CNQ 40-F 2025 (M CAD, real): sin resultado operativo etiquetado.
    rows = {"revenue": 38_762, "income_before_tax": 13_241, "finance_income_cost": -834,
            "depreciation_amortization": 9_384}
    rows.update(over)
    return [_row(m, v) for m, v in rows.items() if v is not None]


def test_cnq_ebitda_pretax_less_net_finance_plus_da():
    ebitda = build_estimates(_cnq_2025())["annual"][0]["ebitda"]
    # 13.241 − (−834) + 9.384 = 23.459 M CAD
    assert ebitda["value"] == 23_459
    assert ebitda["basis"] == "pretax_less_net_finance_result_plus_da"
    assert ebitda["reported"] is False and ebitda["unit"] == "CAD" and ebitda["url"]


def test_airbus_pretax_from_profit_plus_tax():
    # Airbus ESEF 2025 (M EUR, real): sin ProfitLossBeforeTax; beneficio total 4.960 + impuesto 1.390.
    rows = [_row(m, v, unit="EUR") for m, v in {"revenue": 73_420, "net_income_total": 4_960,
                                                 "income_tax_expense": 1_390, "finance_income_cost": 268,
                                                 "depreciation_amortization": 3_133}.items()]
    ebitda = build_estimates(rows)["annual"][0]["ebitda"]
    assert ebitda["value"] == 4_960 + 1_390 - 268 + 3_133 == 9_215
    assert ebitda["basis"] == "pretax_less_net_finance_result_plus_da"


def test_no_net_finance_result_mixed_units_or_lender_give_no_ebitda():
    # Solo gastos financieros (no el neto): «antes de impuestos + gastos financieros» no se presenta como real.
    rows = [*_cnq_2025(finance_income_cost=None), _row("interest_expense", 900)]
    assert build_estimates(rows)["annual"][0]["ebitda"] is None
    mixed = [*_cnq_2025(finance_income_cost=None), _row("finance_income_cost", -834, unit="USD")]
    assert build_estimates(mixed)["annual"][0]["ebitda"] is None
    assert build_estimates(_cnq_2025(), derive_ebitda=False)["annual"][0]["ebitda"] is None


def test_operating_income_still_wins():
    rows = [*_cnq_2025(), _row("operating_income", 14_000)]
    ebitda = build_estimates(rows)["annual"][0]["ebitda"]
    assert ebitda["value"] == 14_000 + 9_384 and ebitda["basis"] == "operating_income_plus_da"


def test_components_alone_do_not_open_periods():
    rows = [*_cnq_2025(), _row("income_before_tax", 1, end=date(2026, 12, 31))]
    assert [p["period_end"] for p in build_estimates(rows)["annual"]] == [END]


def test_lenders_and_insurers_detected():
    def co(**kw):
        return SimpleNamespace(**{"sector": "", "industry": "", "company_type": "operating", **kw})
    assert interest_is_operating(co(sector="Financials", industry="Insurance"))
    assert interest_is_operating(co(industry="Banks - Regional"))
    assert interest_is_operating(co(sic_code="6331"))
    assert not interest_is_operating(co(sector="Energy", industry="Energy"))
    assert not interest_is_operating(co(sector="Financials", industry="Asset management and holdings"))
