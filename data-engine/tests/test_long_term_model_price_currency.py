"""Precio del modelo a largo plazo: sin conversion posible, N/D (no el
cierre crudo en otra divisa).

Calculo independiente: ficha en EUR con cierre de 250 cotizado en USD y sin
tipo USD/EUR guardado -> no hay precio en EUR; antes el modelo usaba 250 como
si fueran EUR (precio y comparables mal por el tipo de cambio). Con cotizacion
en peniques (TSCO.L, 250 GBp) el precio es 2,50 GBP, exacto y sin FX.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, MarketPrice
from app.services.long_term_model_service import LongTermModelService


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        yield session
    engine.dispose()


def _company(db, ticker, currency, close, quote):
    company = Company(ticker=ticker, name=ticker, currency=currency, exchange="X",
                      company_type="operating", valuation_model="standard_dcf")
    db.add(company)
    db.flush()
    db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 29), close=Decimal(close),
                       adj_close=Decimal(close), source="market_close", quote_currency=quote))
    db.flush()
    return company


def test_unconvertible_quote_is_nd_not_raw_close(db):
    company = _company(db, "ASML", "EUR", "250", "USD")
    assert LongTermModelService()._model_price(db, company) == (None, None, None)


def test_pence_quote_converted_to_pounds(db):
    company = _company(db, "TSCO.L", "GBP", "250", "GBp")
    price, as_of, source = LongTermModelService()._model_price(db, company)
    assert price == pytest.approx(2.5)
    assert as_of == "2026-10-29"
    assert source == "market_price"
