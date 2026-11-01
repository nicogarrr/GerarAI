"""Estrés histórico: una posición de Londres no es «otra línea» por cotizar en peniques.

``fill_default_currency`` da a un ``.L`` la divisa ``GBX`` y Yahoo devuelve el
histórico en ``GBp``. La comparación pasaba ambas por ``.upper()`` (``GBX`` vs
``GBP``) y declaraba ``currency_mismatch``: TODA posición de Londres salía
«sin datos» y bloqueaba la cartera entera. Peniques y libras son la misma
línea (los rendimientos no dependen de la escala); otra divisa sigue siendo
otra línea.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.historical_stress_service as stress
from app.models.entities import Base, Company, Position
from tests.test_historical_stress import series


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session
    engine.dispose()


def _add(db, ticker, exchange, currency):
    company = Company(ticker=ticker, name=ticker, exchange=exchange, currency=currency, sector="S", industry="I",
                      company_type="holding", valuation_model="unassigned", special_sources=[], special_risks=[],
                      factor_tags=[])
    db.add(company)
    db.flush()
    db.add(Position(company_id=company.id, quantity=Decimal("1"), market_value_base=Decimal(50),
                    base_currency="EUR", currency=currency, as_of=date(2026, 10, 13)))
    db.commit()


def _report(db, monkeypatch, ticker, yahoo_currency):
    async def load(symbol):
        return {"prices": series(), "source": "Yahoo Finance", "source_url": "https://query1.finance.yahoo.com",
                "fetched_at": "2026-10-13T18:00:00+00:00", "currency": yahoo_currency}

    monkeypatch.setattr(stress, "load_history", load)
    return asyncio.run(stress.HistoricalStressService().build(db, ticker=ticker))


@pytest.mark.parametrize("company_currency", ["GBX", "GBp", "GBP"])
def test_londres_en_peniques_se_calcula(db, monkeypatch, company_currency):
    _add(db, "VOD.L", "LSE", company_currency)
    window = _report(db, monkeypatch, "VOD.L", "GBp")["companies"][0]["windows"][1]
    assert window["status"] == "calculated", window


def test_cartera_con_londres_no_queda_bloqueada(db, monkeypatch):
    _add(db, "VOD.L", "LSE", "GBX")

    async def load(symbol):
        return {"prices": series(), "source": "Yahoo Finance", "source_url": None,
                "fetched_at": "2026-10-13T18:00:00+00:00", "currency": "GBp"}

    monkeypatch.setattr(stress, "load_history", load)
    report = asyncio.run(stress.HistoricalStressService().build(db))
    assert report["portfolio"][1]["status"] == "calculated", report["portfolio"][1]


def test_otra_divisa_sigue_siendo_otra_linea(db, monkeypatch):
    _add(db, "VOD.L", "LSE", "GBX")
    window = _report(db, monkeypatch, "VOD.L", "USD")["companies"][0]["windows"][1]
    assert window["status"] == "SIN_DATOS" and window["reason"] == "currency_mismatch"
