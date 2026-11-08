"""Tasas base de empresas que queman caja junto al valor justo (gerarai-dcavalor4, 7-nov-2026)."""

from datetime import date
from types import SimpleNamespace

from app.models import Document
from app.services import valuation_summary as vs
from app.valuation.cash_burn_base_rate import (
    burns_cash,
    cash_burn_base_rate,
    latest_fiscal_year_values,
)
from tests.test_valuation_summary import company, db, fact  # noqa: F401 - fixture

THESIS = {"value": 24.4, "source": "tesis", "label": "Tesis publicada v3", "publishable": True}


def _f(metric, year, value):
    return SimpleNamespace(metric=metric, year=year, value=value)


def test_cash_burner_with_a_thesis_value_gets_the_measured_base_rate():
    latest = {"fiscal_year": 2025, "net_income": -342.0, "operating_cash_flow": -300.0}
    rate = cash_burn_base_rate(latest, THESIS)
    assert rate is not None
    assert rate["cases"] == 2845
    assert rate["median_return_24m"] == -0.51
    assert rate["median_return_24m_by_period"] == {"2014_2018": -0.41, "2019_2024": -0.52}
    assert rate["fell_over_half_24m_share"] == 0.50
    assert rate["beat_spy_24m_share"] == 0.21
    assert rate["message_es"] == (
        "Punto de partida: la empresa aún pierde dinero y quema caja. En el backtest "
        "(2.845 casos así en EE. UU., 2014–2026, contando las que desaparecieron), a 2 años "
        "la rentabilidad mediana fue -51 %: la mitad cayó más de un 50 %, el 11 % más que "
        "duplicó y solo el 21 % batió al S&P 500. No cambia esta cifra."
    )
    assert rate["message_en"].startswith("Starting point: the company still loses money")


def test_no_line_without_a_figure_or_without_cash_burn():
    burning = {"net_income": -1.0, "operating_cash_flow": -1.0}
    assert cash_burn_base_rate(burning, {"value": None}) is None
    assert cash_burn_base_rate(burning, {"value": True}) is None
    assert cash_burn_base_rate({"net_income": -1.0, "operating_cash_flow": 5.0}, THESIS) is None
    assert cash_burn_base_rate({"net_income": 3.0, "operating_cash_flow": -5.0}, THESIS) is None
    assert cash_burn_base_rate({}, THESIS) is None
    assert not burns_cash({"net_income": -1.0})


def test_latest_complete_fiscal_year_never_mixes_years():
    facts = [_f("net_income", 2025, -10), _f("operating_cash_flow", 2024, -5),
             _f("net_income", 2024, 7), _f("revenue", 2025, 100)]
    assert latest_fiscal_year_values(facts) == {"fiscal_year": 2024, "net_income": 7.0, "operating_cash_flow": -5.0}
    assert latest_fiscal_year_values([]) == {}


def test_build_summaries_attaches_it_next_to_the_thesis_value(db, monkeypatch):  # noqa: F811
    c = company(db)
    doc = Document(company_id=c.id, title="10-K", source_url="https://www.sec.gov/filing", source_type="SEC", tenant_id=1)
    db.add(doc)
    db.flush()
    fact(db, c, doc, metric="net_income", value=-342)
    fact(db, c, doc, metric="operating_cash_flow", value=-300)
    monkeypatch.setattr(vs, "resolve_fair_values", lambda _db, comps, today=None: {x.id: dict(THESIS) for x in comps})
    out = vs.build_summaries(db, [c], today=date(2026, 10, 29))["TEST"]
    assert out["fair_value"]["value"] == 24.4
    assert out["base_rate"]["fiscal_year"] == 2025
    assert out["base_rate"]["median_return_24m"] == -0.51
