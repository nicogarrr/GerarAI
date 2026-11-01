"""Libro de divisas (renta): operaciones de Londres en peniques («GBp»).

El libro de libras juntaba las operaciones con ``currency.upper() == "GBP"``,
así que una venta de 10 acciones a 5.000 peniques entraba como 50.000 libras
de entrada de divisa (no 500): quedaban «49.700 GBP sin convertir» y la compra
en peniques consumía ×100 libras de los lotes.
"""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FxConversion, FXRate, Portfolio, Tenant, Transaction
from app.services.tax_report_service import TaxReportService


def _db(rows):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    t = Tenant(external_id="pence", name="pence")
    s.add(t)
    s.flush()
    s.info["tenant_id"] = t.id
    s.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    for day, rate in ((date(2025, 1, 6), "1.20"), (date(2025, 3, 2), "1.25"), (date(2025, 2, 3), "1.22")):
        s.add(FXRate(base_currency="EUR", quote_currency="GBP", rate_date=day, rate=D(rate), source="ECB"))
    c = Company(ticker="BBB.L", name="BBB", exchange="LSE", currency="GBp", sector="S", industry="I",
                company_type="holding", valuation_model="unassigned", special_sources=[],
                special_risks=[], factor_tags=[], domicile_country="GB")
    s.add(c)
    s.flush()
    for day, action, qty, price in rows:
        s.add(Transaction(company_id=c.id, trade_date=day, action=action, quantity=D(qty), price=D(price),
                          fees=D(0), currency="GBp", raw_payload={}))
    s.add(FxConversion(trade_date=date(2025, 3, 2), disposed_currency="GBP", disposed_amount=D(300),
                       acquired_currency="EUR", acquired_amount=D(375), raw_payload={}))
    s.commit()
    return s


def _gbp(s):
    return TaxReportService().compute_report(s, 2025, fx_opening_complete=True)["summary"]["currency_ledger_by_currency"]["GBP"]


@pytest.mark.parametrize("price", ["5000"])
def test_sale_in_pence_enters_pounds_not_pence(price):
    # 10 x 5.000 p = 500 £ (valen 600 € al 1,20); se convierten 300 £ -> coste 360 €,
    # transmisión 375 € -> +15 €; quedan 200 £.
    gbp = _gbp(_db([(date(2025, 1, 6), "sell", "10", price)]))
    assert gbp["unconverted"] == 200.0
    assert gbp["gain_base"] == 15.0 and gbp["status"] == "computed"


def test_buy_in_pence_consumes_pounds_not_pence():
    # Venta 10 x 5.000 p (+500 £), compra 2 x 5.000 p (-100 £), conversión 300 £: quedan 100 £.
    gbp = _gbp(_db([(date(2025, 1, 6), "sell", "10", "5000"), (date(2025, 2, 3), "buy", "2", "5000")]))
    assert gbp["unconverted"] == 100.0
    assert gbp["status"] == "computed"
