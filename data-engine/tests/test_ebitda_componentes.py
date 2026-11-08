"""EBITDA por componentes cuando el emisor no etiqueta el resultado operativo (CNQ 40-F, Airbus ESEF).

Cifras de CNQ FY2024 (40-F, ifrs-full, millones de CAD): beneficio antes de impuestos 8.270,
gastos financieros 1.110 (FinanceCosts), amortizaciones 6.940 (DepreciationAndAmortisationExpense).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import financial_ingestion_service as fis
from app.services import shareholder_irr_service as svc
from app.valuation.ebitda_components import (
    OPERATING_PLUS_DA,
    PRETAX_COMPONENTS,
    PRETAX_NET_FINANCE,
    REPORTED,
    ebitda_from_components,
    pretax_income,
)


def test_orden_operativo_luego_fuente_luego_componentes():
    assert ebitda_from_components(operating_income=100.0, depreciation_amortization=-30.0) == (130.0, OPERATING_PLUS_DA)
    assert ebitda_from_components(operating_income=None, depreciation_amortization=30.0,
                                  ebitda_reported=125.0, income_before_tax=90.0, interest_expense=10.0) == (125.0, REPORTED)
    assert ebitda_from_components(operating_income=None, depreciation_amortization=6940.0,
                                  income_before_tax=8270.0, interest_expense=-1110.0) == (16320.0, PRETAX_COMPONENTS)
    assert ebitda_from_components(operating_income=None, depreciation_amortization=None,
                                  income_before_tax=8270.0, interest_expense=1110.0) == (None, None)


def _cite(v, year, metric):
    return {"value": v * 1_000_000, "unit": "CAD", "period": f"{year}-12-31:FY", "metric": metric,
            "source_type": "SEC", "is_reported": True}


def test_starting_point_de_un_filer_ifrs_sin_resultado_operativo_va_por_ev_ebitda(monkeypatch):
    years = [2022, 2023, 2024]
    data = {
        "revenue": [43_000.0, 36_500.0, 35_900.0],
        "income_before_tax": [14_400.0, 10_600.0, 8_270.0],
        "interest_expense": [720.0, 1_010.0, 1_110.0],
        "depreciation_amortization": [5_500.0, 5_900.0, 6_940.0],
        "net_income": [10_900.0, 8_200.0, 6_100.0],
        "shares_diluted": [1_110.0, 1_090.0, 1_070.0],
        "operating_cash_flow": [17_000.0, 12_400.0, 14_400.0],
        "capital_expenditure": [4_900.0, 5_200.0, 5_500.0],
    }
    annual = {m: {y: _cite(v, y, m) for y, v in zip(years, vals, strict=True)} for m, vals in data.items()}
    annual["shares_diluted"] = {y: {**c, "unit": "shares"} for y, c in annual["shares_diluted"].items()}
    point = {"cash_and_equivalents": _cite(130.0, 2024, "cash_and_equivalents"),
             "total_debt": _cite(16_617.0, 2024, "total_debt")}
    monkeypatch.setattr(svc, "company_facts", lambda db, company: (annual, point))
    import app.services.user_sotp_service as us

    monkeypatch.setattr(us, "_price", lambda db, company: (45.0, "CAD", "2025-03-31"))
    company = SimpleNamespace(ticker="CNQ", currency="CAD", sector="Energy", industry="Oil & Gas E&P",
                              company_type="cyclical", sic_code=1311)
    sp, _hist, warnings, cites = svc.starting_point(None, company, today=date(2025, 4, 1))  # type: ignore[arg-type]
    # Antes: sin resultado operativo no había EBITDA y el método era PER (tir_per).
    assert cites["method"]["chosen"] == "tir_ev_ebitda"
    assert sp.basis == "ev_ebitda"
    assert sp.ebitda == pytest.approx(8_270.0 + 1_110.0 + 6_940.0)
    assert cites["ebitda_basis"]["years"] == years
    assert "gastos financieros" in sp.sources["ebitda"]
    assert any("EBITDA derivado" in w for w in warnings)


def test_airbus_sin_beneficio_antes_de_impuestos_etiquetado():
    """Airbus FY2024 (ESEF, millones de EUR): ProfitLoss 4.078, IncomeTaxExpenseContinuingOperations 1.347,
    FinanceIncomeCost +121 (ingreso neto), AdjustmentsForDepreciationAndAmortisationExpense 2.853."""
    pbt = pretax_income(income_before_tax=None, profit_loss=4078.0, income_tax_expense=1347.0)
    assert pbt == 5425.0
    assert ebitda_from_components(operating_income=None, depreciation_amortization=2853.0, income_before_tax=pbt,
                                  interest_expense=900.0, net_finance_result=121.0) == (5425.0 - 121.0 + 2853.0,
                                                                                         PRETAX_NET_FINANCE)
    assert pretax_income(income_before_tax=8270.0, profit_loss=1.0, income_tax_expense=1.0) == 8270.0


def test_componentes_mapeados_en_la_ingesta():
    esef = {m: c for m, c, _ in fis.ESEF_METRIC_MAP}
    assert esef["net_income_total"] == ["ifrs-full:ProfitLoss"]
    assert esef["finance_income_cost"] == ["ifrs-full:FinanceIncomeCost"]
    ifrs = {m: c for m, c, _ in fis.SEC_IFRS_METRIC_MAP}
    assert ifrs["finance_income_cost"] == ["FinanceIncomeCost"]
    assert fis.SEC_INGESTION_RULES_VERSION >= 6 and fis.ESEF_INGESTION_RULES_VERSION >= 4


def _ifrs_payload(rows):
    """companyfacts ifrs-full mínimo (40-F): rows = (concept, start, end, val, unit)."""
    facts: dict = {"ifrs-full": {}}
    for concept, start, end, val, unit in rows:
        node = facts["ifrs-full"].setdefault(concept, {"units": {}})
        r = {"end": end, "val": val, "filed": f"{int(end[:4]) + 1}-03-01", "form": "40-F"}
        if start:
            r["start"] = start
        node["units"].setdefault(unit, []).append(r)
    return {"facts": facts}


def test_arnes_pit_usa_el_mismo_ebitda_por_componentes_que_la_app():
    from app.valuation import irr_pit_backtest as bt

    rows = []
    for y, rev, pbt, fin, da in ((2022, 43_000, 14_400, 720, 5_500), (2023, 36_500, 10_600, 1_010, 5_900),
                                 (2024, 35_900, 8_270, 1_110, 6_940)):
        s, e = f"{y}-01-01", f"{y}-12-31"
        rows += [("Revenue", s, e, rev * 1e6, "CAD"), ("ProfitLossBeforeTax", s, e, pbt * 1e6, "CAD"),
                 ("FinanceCosts", s, e, fin * 1e6, "CAD"), ("DepreciationAndAmortisationExpense", s, e, da * 1e6, "CAD"),
                 ("ProfitLossAttributableToOwnersOfParent", s, e, pbt * 0.75e6, "CAD"),
                 ("AdjustedWeightedAverageShares", s, e, 1_070e6, "shares")]
    rows.append(("CashAndCashEquivalents", None, "2024-12-31", 3_000e6, "CAD"))  # sin caja el arnés descarta la fecha
    facts = bt.facts_from_companyfacts(_ifrs_payload(rows))
    t = date(2025, 6, 30)
    inp = bt.build_inputs(bt.as_of(facts, t), t=t, price=45.0, splits=[], financial=False, currency="CAD")
    # antes: sin resultado operativo no había EBITDA y el arnés valoraba por PER, a diferencia de la app
    assert inp.method["chosen"] == "tir_ev_ebitda"
    assert inp.start.ebitda == pytest.approx(8_270 + 1_110 + 6_940)
