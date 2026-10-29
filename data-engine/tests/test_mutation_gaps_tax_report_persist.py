"""Supervivientes de mutacion en ``get_report`` / ``regenerate_report`` (ronda 3).

Que se reenvian las opciones del calculo, que se persiste todo el informe
(incluida la caja miscelanea) y que el estado de version distingue un informe
guardado de uno calculado al vuelo. Sin cambios de criterio fiscal.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, Portfolio, TaxReport, Transaction
from app.models.entities import Base
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Portfolio(name="P", base_currency="EUR", is_default=True))
        session.flush()
        company = Company(ticker="AAA", name="AAA", exchange="XETRA", currency="EUR", sector="S",
                          industry="I", company_type="holding", valuation_model="unassigned",
                          special_sources=[], special_risks=[], factor_tags=[])
        session.add(company)
        session.flush()
        session.add(Transaction(portfolio_id=session.query(Portfolio).one().id, company_id=company.id,
                                trade_date=date(2026, 3, 15), action="fee", quantity=Decimal("1"),
                                price=Decimal("-3"), fees=Decimal("0"), currency="EUR",
                                external_id="fee-1", raw_payload={}))
        session.commit()
        yield session


def test_regenerate_forwards_the_fx_options(db, monkeypatch):
    service = TaxReportService()
    seen = {}
    real = service.compute_report

    def spy(db_, year, **kwargs):
        seen.update(kwargs)
        return real(db_, year, **kwargs)

    monkeypatch.setattr(service, "compute_report", spy)
    service.regenerate_report(db, 2026, fx_opening_complete=True, fx_income_by_analogy=True)
    assert seen["fx_opening_complete"] is True
    assert seen["fx_income_by_analogy"] is True


def test_regenerate_persists_the_whole_report(db):
    data = TaxReportService().regenerate_report(db, 2026)
    row = db.query(TaxReport).one()
    assert row.portfolio_id == db.query(Portfolio).one().id
    assert row.base_currency == "EUR"
    assert row.misc == data["misc"] and len(row.misc) == 1
    assert row.generated_at is not None
    assert data["persisted"] is True
    assert data["versioning"]["persisted"] is True
    assert data["generated_at"].startswith(str(row.generated_at.year))


def test_regenerate_twice_updates_the_same_row(db):
    service = TaxReportService()
    service.regenerate_report(db, 2026)
    service.regenerate_report(db, 2026)
    assert db.query(TaxReport).count() == 1


def test_get_report_on_a_saved_report_passes_tme_and_marks_it_persisted(db, monkeypatch):
    service = TaxReportService()
    service.regenerate_report(db, 2026)
    seen = {}
    real = service._build_filing

    def spy(db_, year, data, tme=None):
        seen["tme"] = tme
        return real(db_, year, data, tme=tme)

    monkeypatch.setattr(service, "_build_filing", spy)
    data = service.get_report(db, 2026, tme=Decimal("1.5"))
    assert seen["tme"] == Decimal("1.5")
    assert data["persisted"] is True
    assert data["versioning"]["persisted"] is True
    assert data["misc"] and data["misc"][0]["type"] == "fee"
    assert data["generated_at"] is not None


def test_get_report_without_a_saved_report_is_computed_and_not_persisted(db):
    data = TaxReportService().get_report(db, 2026)
    assert data["persisted"] is False
    assert data["generated_at"] is None
    assert data["versioning"]["persisted"] is False
    assert db.query(TaxReport).count() == 0
