from dataclasses import replace
from datetime import date

import pytest

from app.services.financial_health import HealthFact, calculate_health

TODAY = date(2026, 10, 29)


def sample():
    values = {
        2023: {"total_assets": 100},
        2024: {"total_assets": 110, "net_income": 5, "long_term_debt": 30,
               "current_assets": 50, "current_liabilities": 30, "gross_profit": 30, "revenue": 100},
        2025: {"total_assets": 120, "net_income": 12, "long_term_debt": 20,
               "operating_cash_flow": 15, "current_assets": 70, "current_liabilities": 30,
               "gross_profit": 44, "revenue": 130, "common_stock_issued": 0,
               "retained_earnings": 40, "income_before_tax": 16, "interest_expense": 2,
               "total_equity": 70, "total_liabilities": 50},
    }
    facts = []
    for year, metrics in values.items():
        for metric, value in metrics.items():
            facts.append(HealthFact(len(facts)+1, metric, year, value, "USD", date(year, 12, 31), "https://www.sec.gov/test", "SEC", 1))
    return facts


def calc(facts=None, **kw):
    return calculate_health(sample() if facts is None else facts, sector=kw.pop("sector", "Industrials"), company_type=kw.pop("company_type", "listed"), today=kw.pop("today", TODAY), **kw)


def test_nine_signals_source_citable_and_exact_formulas():
    out = calc()
    assert out["piotroski"]["score"] == 9
    assert out["piotroski"]["evaluated"] == 9
    for signal in out["piotroski"]["signals"]:
        assert signal["formula"] and signal["evidence"]
        assert all(f["fact_id"] and f["source_url"] for f in signal["evidence"])
    assert out["altman"]["score"] == pytest.approx(round(6.56*40/120 + 3.26*40/120 + 6.72*18/120 + 1.05*70/50, 4))


@pytest.mark.parametrize("sector", ["Financials", "Unknown", "Real Estate", "Insurance"])
def test_excluded_sectors(sector):
    assert calc(sector=sector)["piotroski"]["score"] is None


def test_pre_revenue():
    assert calc(company_type="pre_revenue")["status"] == "not_evaluable"


def test_missing_is_not_zero_and_no_partial_score():
    out = calc([f for f in sample() if f.metric != "common_stock_issued"])
    assert out["piotroski"]["score"] is None
    assert out["piotroski"]["evaluated"] == 8
    assert out["piotroski"]["signals"][6]["point"] is None
    assert out["altman"]["status"] == "ok"


def test_issuance_and_bad_signals_are_zero():
    facts = [replace(f, value=100) if f.year == 2025 and f.metric == "common_stock_issued" else f for f in sample()]
    assert calc(facts)["piotroski"]["score"] == 8


@pytest.mark.parametrize("change", [{"value": float("nan")}, {"value": float("inf")}, {"source_url": ""}, {"source_type": "seed"}])
def test_invalid_inputs(change):
    facts = [replace(f, **change) if f.metric == "common_stock_issued" else f for f in sample()]
    assert calc(facts)["piotroski"]["score"] is None


def test_empty_future_stale_and_incoherent():
    assert calc([])["reason"] == "Sin ejercicios anuales con fuente"
    assert calc(today=date(2030, 1, 1))["status"] == "not_evaluable"
    assert calc([replace(f, period_end=date(2027, 1, 1)) for f in sample()])["status"] == "not_evaluable"
    assert calc([replace(f, period_end=date(2025, 11, 1)) if f.metric == "retained_earnings" else f for f in sample()])["status"] == "not_evaluable"


def test_currency_periods_denominators_and_missing_altman():
    for changes in ({"value": 0}, {"unit": "EUR"}, {"period_end": date(2023, 2, 1)}):
        facts = [replace(f, **changes) if f.metric == "total_assets" and f.year == 2023 else f for f in sample()]
        assert calc(facts)["piotroski"]["score"] is None
    out = calc([f for f in sample() if f.metric != "retained_earnings"])
    assert out["altman"]["score"] is None
    assert out["piotroski"]["score"] == 9


def test_health_calculation_does_not_mutate_evidence():
    facts = sample()
    original = list(facts)
    first = calc(facts)
    assert facts == original
    assert calc(facts) == first


def test_formulas_shown_on_ficha_use_spanish_labels():
    """La notación de las fórmulas se muestra en la ficha: etiquetas en
    español, no abreviaturas inglesas (GP, sales, CFO, LTD, CA/CL,
    common_stock_issued, book_equity...)."""
    import re

    out = calc()
    formulas = [s["formula"] for s in out["piotroski"]["signals"]]
    formulas.append(out["altman"]["formula"])
    english = re.compile(
        r"\b(GP|sales|NI|CFO|LTD|avgA|CA|CL|WC|RE|A)\(|\b(common_stock_issued|book_equity|liabilities|sales)\b|/A\b"
    )
    leaks = [f for f in formulas if english.search(f)]
    assert leaks == []
    assert any("Beneficio bruto(t) / Ventas(t)" in f for f in formulas)
    assert any("Emisión de acciones ordinarias(t) = 0" in f for f in formulas)
