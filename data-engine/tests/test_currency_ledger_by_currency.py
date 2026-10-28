"""Libro de divisas multidivisa: filas con divisa, agregado por divisa y total EUR aparte."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FxConversion, FXRate, Portfolio, Tenant, Transaction
from app.services.tax_report_service import TaxReportService


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    t = Tenant(external_id="multi", name="multi")
    s.add(t)
    s.flush()
    s.info["tenant_id"] = t.id
    s.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    for quote, rows in {"USD": [(date(2025, 1, 5), "0.90"), (date(2025, 3, 1), "0.95")],
                        "GBP": [(date(2025, 1, 6), "1.20"), (date(2025, 3, 2), "1.25")]}.items():
        for day, rate in rows:
            s.add(FXRate(base_currency="EUR", quote_currency=quote, rate_date=day, rate=D(rate), source="ECB"))
    for ticker, cur in (("AAA", "USD"), ("BBB", "GBP")):
        c = Company(ticker=ticker, name=ticker, exchange="X", currency=cur, sector="S", industry="I",
                    company_type="holding", valuation_model="unassigned", special_sources=[],
                    special_risks=[], factor_tags=[], domicile_country="US")
        s.add(c)
        s.flush()
        s.add(Transaction(company_id=c.id, trade_date=date(2025, 1, 5 if cur == "USD" else 6), action="sell",
                          quantity=D(10), price=D(120 if cur == "USD" else 50), fees=D(0), currency=cur, raw_payload={}))
    s.add(FxConversion(trade_date=date(2025, 3, 1), disposed_currency="USD", disposed_amount=D(1000),
                       acquired_currency="EUR", acquired_amount=D(950), raw_payload={}))
    s.add(FxConversion(trade_date=date(2025, 3, 2), disposed_currency="GBP", disposed_amount=D(300),
                       acquired_currency="EUR", acquired_amount=D(375), raw_payload={}))
    s.commit()
    return s


def _ledger(db, **kw):
    svc = TaxReportService()
    return svc.compute_report(db, 2025, fx_opening_complete=True, **kw)


def test_summary_has_per_currency_aggregate_and_separate_eur_total(db):
    s = _ledger(db)["summary"]
    by = s["currency_ledger_by_currency"]
    assert set(by) == {"USD", "GBP"}
    # USD: 1200 USD valen 1080 EUR; se convierten 1000 -> coste 900, transmision 950 -> +50; quedan 200 USD
    assert by["USD"]["gain_base"] == 50.0 and by["USD"]["unconverted"] == 200.0 and by["USD"]["status"] == "computed"
    # GBP: 500 GBP valen 600 EUR; se convierten 300 -> coste 360, transmision 375 -> +15; quedan 200 GBP
    assert by["GBP"]["gain_base"] == 15.0 and by["GBP"]["unconverted"] == 200.0 and by["GBP"]["status"] == "computed"
    assert s["currency_ledger_gain_base"] == 65.0  # total EUR aparte, no mezcla unidades


def test_every_row_carries_its_currency_and_unconverted_is_per_currency(db):
    svc = TaxReportService()
    from sqlalchemy import select
    rows = db.execute(
        select(Transaction, Company).outerjoin(Company, Transaction.company_id == Company.id)
    ).all()
    result = svc._currency_ledger(db, rows, lambda cur, day: None, "EUR", date(2025, 1, 1), date(2025, 12, 31), None, True)
    assert {row["currency"] for row in result["rows"]} == {"USD", "GBP"}
    assert result["unconverted"] == {"USD": 200.0, "GBP": 200.0}
    assert "blocked_loss_base" in result["by_currency"]["USD"] and result["by_currency"]["USD"]["gain_base"] is None


def test_one_incomplete_currency_keeps_the_other_visible_and_total_none(db):
    db.add(FxConversion(trade_date=date(2025, 4, 1), disposed_currency="GBP", disposed_amount=D(900),
                        acquired_currency="EUR", acquired_amount=D(1000), raw_payload={}))  # supera la divisa conocida
    db.commit()
    s = _ledger(db)["summary"]
    by = s["currency_ledger_by_currency"]
    assert by["USD"]["status"] == "computed" and by["USD"]["gain_base"] == 50.0
    assert by["GBP"]["status"] == "incomplete" and by["GBP"]["gain_base"] is None
    assert s["currency_ledger_status"] == "incomplete" and s["currency_ledger_gain_base"] is None


def test_no_conversions_has_no_by_currency(db):
    db.query(FxConversion).delete()
    db.commit()
    s = _ledger(db)["summary"]
    assert s["currency_ledger_status"] == "not_computed"
    assert s["currency_ledger_by_currency"] == {}
