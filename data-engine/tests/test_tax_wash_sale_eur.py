"""DGT: se calcula la ganancia en moneda nativa y se convierte al vender.

El movimiento de USD/EUR no crea una pérdida en la venta de acciones con
beneficio nativo. 10 x (105 - 100) USD a 0,90 = 45 EUR. Por tanto una compra
posterior no difiere una pérdida inexistente; el lote nuevo conserva 936 EUR
de coste convertido al vender a 0,90. Sustituye las expectativas previas de
-55 EUR que mezclaban ambas fechas FX; cualquier venta de divisa es aparte.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _setup(db: Session) -> Company:
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = Company(
        ticker="USX", name="USX", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2025, 1, 10), rate=Decimal("1.00"), source="test"))
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2025, 3, 3), rate=Decimal("0.90"), source="test"))
    db.commit()
    return company


def _tx(db, company, day, action, qty, price):
    _carry_fx_to(db, day)
    db.add(Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)),
        fees=Decimal("0"), currency="USD",
    ))
    db.commit()


def _sales(report, ticker="USX"):
    row = next(r for r in report["realized"] if r["ticker"] == ticker)
    return row, row["sales"]


def test_ganancia_nativa_no_crea_perdida_por_fx_ni_bloqueo(db):
    c = _setup(db)
    _tx(db, c, date(2025, 1, 10), "buy", 10, 100)
    _tx(db, c, date(2025, 3, 3), "sell", 10, 105)
    _tx(db, c, date(2025, 3, 20), "buy", 10, 104)  # recompra dentro de 2 meses
    _tx(db, c, date(2025, 12, 1), "buy", 1, 104)  # cierra la ventana de datos

    report = TaxReportService().compute_report(db, 2025)
    row, sales = _sales(report)
    (march,) = sales
    assert march["gain_native"] == 50.0  # en dólares, ganancia
    assert march["wash_sale_blocked"] is False
    assert march["blocked_loss_base"] == 0.0
    assert march["gain_base"] == 45.0
    assert row["gain_base"] == 45.0


def test_recompra_no_hereda_perdida_fx_inexistente(db):
    c = _setup(db)
    _tx(db, c, date(2025, 1, 10), "buy", 10, 100)
    _tx(db, c, date(2025, 3, 3), "sell", 10, 105)
    _tx(db, c, date(2025, 3, 20), "buy", 10, 104)
    _tx(db, c, date(2025, 7, 1), "sell", 10, 104)  # vende el lote recomprado
    _tx(db, c, date(2025, 12, 1), "buy", 1, 104)  # >2 meses después: no bloquea

    report = TaxReportService().compute_report(db, 2025)
    row, sales = _sales(report)
    march, july = sales
    assert march["gain_base"] == 45.0
    assert july["cost_base"] == 936.0
    assert july["gain_base"] == 0.0
    assert row["gain_base"] == 45.0


def _carry_fx_to(db, day) -> None:
    """#2349: el informe solo acepta un tipo de hasta 7 días antes. Estos tests
    son anteriores y fijaban un único tipo semanas atrás; se replica el último
    tipo publicado en la fecha de cada operación para conservar su intención
    (el cálculo con ese tipo), no la antigüedad del dato."""
    from sqlalchemy import desc as _desc
    from sqlalchemy import select as _select

    for quote in ("USD",):
        prior = db.scalar(
            _select(FXRate).where(FXRate.base_currency == "EUR", FXRate.quote_currency == quote,
                                  FXRate.rate_date <= day).order_by(_desc(FXRate.rate_date)).limit(1)
        )
        if prior is not None and prior.rate_date != day:
            db.add(FXRate(base_currency="EUR", quote_currency=quote, rate_date=day,
                          rate=prior.rate, source=prior.source))
