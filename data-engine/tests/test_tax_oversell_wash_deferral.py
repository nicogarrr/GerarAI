"""Una perdida nacida de una venta descubierta no se difiere como cifra conocida.

Hallado con Hypothesis (tests/property/test_prop_tax_fifo.py): una venta con
over_sell valora el exceso a coste cero, asi que su resultado es desconocido.
Si ese resultado sale negativo y hay recompra en los 2 meses, el motor difería
esa perdida inventada al lote recomprado, y la venta de ese lote al año
siguiente publicaba coste y ganancia en euros como si fueran exactos (sin
over_sell, sin missing_fx, con total de plusvalias y casillas numéricos).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Portfolio, Transaction
from app.services.tax_report_service import TaxReportService, replay_tax_fifo


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _seed(db):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = Company(
        ticker="OVW", name="OVW", exchange="BME", currency="EUR",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    for day, action, qty, price in (
        (date(2025, 1, 10), "buy", 10, 100),
        (date(2025, 3, 1), "sell", 12, 50),   # over_sell de 2: resultado desconocido
        (date(2025, 3, 15), "buy", 10, 50),   # recompra dentro de los 2 meses
        (date(2026, 6, 1), "sell", 10, 60),   # vende el lote recomprado
    ):
        db.add(Transaction(
            company_id=company.id, trade_date=day, action=action,
            quantity=Decimal(qty), price=Decimal(price), fees=Decimal("0"), currency="EUR",
        ))
    db.commit()


def test_replay_marks_the_lot_fed_by_an_over_sell_loss_as_unknown(db):
    _seed(db)
    events = list(db.query(Transaction).order_by(Transaction.trade_date))
    _, sales = replay_tax_fifo(events, lambda _c, _d: Decimal("1"), date(2026, 1, 1), date(2026, 12, 31))
    (entry,) = sales
    assert entry["over_sell"] is False
    assert entry["cost_unknown"] is True
    assert entry["cost_base"] is None
    assert entry["gain_base_raw"] is None


def test_next_year_sale_of_that_lot_publishes_no_invented_cost_or_gain(db):
    _seed(db)
    report = TaxReportService().compute_report(db, 2026)
    (bucket,) = report["realized"]
    (sale,) = bucket["sales"]
    assert sale["proceeds_native"] == 600.0  # la transmision es un dato observado
    assert sale["cost_native"] is None
    assert sale["cost_base"] is None
    assert sale["gain_native"] is None
    assert sale["gain_base"] is None
    assert sale["cost_unknown"] is True
    assert bucket["cost_native"] is None and bucket["gain_base"] is None
    assert bucket["cost_unknown"] is True
    # no es un problema de tipo de cambio: la etiqueta no puede mentir
    assert bucket["missing_fx"] is False
    summary = report["summary"]
    assert summary["total_realized_gain_base"] is None
    assert summary["net_taxable_base"] is None
    assert summary["cost_unknown"] == ["OVW"]


def test_the_over_sell_year_itself_still_reports_the_sale_as_over_sell(db):
    _seed(db)
    report = TaxReportService().compute_report(db, 2025)
    bucket = report["realized"][0]
    assert bucket["over_sell"] is True
    assert bucket["missing_fx"] is False
