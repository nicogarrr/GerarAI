"""Ramas sin cubrir de app/api/routes/investors.py: vista inversa de holders
(acierto y 404) y 404 del portfolio de un inversor desconocido."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.investors import holders_by_ticker_route, investor_portfolio_route
from app.models import Company
from app.models.entities import Base


def _db() -> Session:
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    db.add(
        Company(
            ticker="AAPL",
            name="Apple",
            exchange="NASDAQ",
            company_type="mature",
            valuation_model="dcf",
            isin="US0378331005",
        )
    )
    db.commit()
    db.info["tenant_id"] = 1
    return db


def test_holders_route_devuelve_la_vista_inversa_del_ticker():
    result = holders_by_ticker_route("AAPL", _db())
    assert result["ticker"] == "AAPL"
    assert result["cusip"] == "037833100"
    assert result["holders"] == []


def test_holders_route_404_si_el_ticker_no_existe():
    with pytest.raises(HTTPException) as excinfo:
        holders_by_ticker_route("NOPE", _db())
    assert excinfo.value.status_code == 404


def test_investor_portfolio_route_404_si_el_inversor_no_existe():
    with pytest.raises(HTTPException) as excinfo:
        investor_portfolio_route("no-existe", _db())
    assert excinfo.value.status_code == 404
