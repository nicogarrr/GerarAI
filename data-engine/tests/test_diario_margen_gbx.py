"""Diario: margen frente al precio de ejecución en una ficha de Londres en «GBX».

Las fichas de Londres llevan la divisa en subunidad («GBX», de
fill_default_currency) y el valor justo del motor/tesis va en libras (divisa
principal, como en watchlist y screener). Una compra a 2.650 GBp contra un
valor de 30 £ salía con margen −98,9 % (peniques contra libras) en vez de
+13,2 %.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, ValuationModel, ValuationOutput
from app.services.journal_trade_link import fair_value_on


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, currency: str) -> Company:
    company = Company(ticker="PNCJ.L", name="PNCJ", exchange="LSE", currency=currency, sector="Retail",
                      industry="Retail", company_type="standard", valuation_model="standard_dcf",
                      special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.commit()
    model = ValuationModel(company_id=company.id, model_type="standard_dcf", version=1, status="final",
                           calculation_trace={}, created_at=datetime(2026, 3, 1, tzinfo=UTC),
                           updated_at=datetime(2026, 3, 1, tzinfo=UTC))
    db.add(model)
    db.flush()
    db.add(ValuationOutput(valuation_model_id=model.id, scenario="base", value_per_share=Decimal("1"),
                           output_payload={"expected_value": 30.0}))
    db.commit()
    return company


@pytest.mark.parametrize(("company_currency", "price", "trade_currency"),
                         [("GBX", "2650", "GBp"), ("GBX", "2650", "GBX"), ("GBX", "26.50", "GBP"),
                          ("GBP", "2650", "GBp"), ("GBP", "26.50", "GBP")])
def test_margin_compares_pounds_with_pounds(db, company_currency, price, trade_currency):
    company = _company(db, company_currency)
    reading = fair_value_on(db, company, date(2026, 3, 12), price=Decimal(price), currency=trade_currency)
    assert reading is not None
    assert reading["value"] == 30.0
    assert reading["margin_vs_trade_price"] == pytest.approx(30 / 26.5 - 1)
    assert reading["note"] is None


def test_other_currency_still_has_no_margin(db):
    company = _company(db, "GBX")
    reading = fair_value_on(db, company, date(2026, 3, 12), price=Decimal("33"), currency="USD")
    assert reading is not None
    assert reading["margin_vs_trade_price"] is None
