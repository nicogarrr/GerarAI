"""Regla de los 2 meses (art. 33.5.f LIRPF) evaluada sobre la pérdida en EUROS.

La pérdida patrimonial que la ley difiere es la del IRPF, que se calcula en
euros: valor de adquisición convertido al tipo de la fecha de compra y valor
de transmisión al tipo de la fecha de venta (art. 34 y 35 LIRPF; Manual Renta
2025, cap. 11). Una venta con GANANCIA en dólares puede ser una PÉRDIDA en
euros si el dólar se ha depreciado: esa pérdida en euros también queda
bloqueada si se recompran valores homogéneos en los 2 meses anteriores o
posteriores.

Cálculo a mano (tipo = EUR por 1 USD):
  10/01/2025 compra 10 x 100 $ a 1,00  -> coste 1.000,00 €
  03/03/2025 venta  10 x 105 $ a 0,90  -> transmisión 945,00 €
             en dólares: +50 $ (ganancia); en euros: 945 - 1.000 = -55,00 €
  20/03/2025 recompra 10 x 104 $ a 0,90 (17 días después) -> 936,00 €
  => la pérdida de 55,00 € NO es computable en la venta de marzo: se difiere
     al lote recomprado (coste fiscal 936 + 55 = 991,00 €).
  01/07/2025 venta del lote recomprado 10 x 104 $ a 0,90 -> 936,00 €
             resultado: 936 - 991 = -55,00 € (computable: sin recompra después)
  Total computable del ejercicio: 0 + (-55,00) = -55,00 €.

Sin la corrección, la venta de marzo se declaraba como pérdida computable de
-55 € (la regla solo miraba el signo en dólares) y el total del año salía igual
pero con la pérdida imputada en la venta equivocada; y si la recompra sigue en
cartera a 31/12, el año declaraba -55 € que la ley no permite computar.
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


def test_perdida_en_euros_con_ganancia_en_dolares_se_bloquea_si_hay_recompra(db):
    c = _setup(db)
    _tx(db, c, date(2025, 1, 10), "buy", 10, 100)
    _tx(db, c, date(2025, 3, 3), "sell", 10, 105)
    _tx(db, c, date(2025, 3, 20), "buy", 10, 104)  # recompra dentro de 2 meses
    _tx(db, c, date(2025, 12, 1), "buy", 1, 104)  # cierra la ventana de datos

    report = TaxReportService().compute_report(db, 2025)
    row, sales = _sales(report)
    (march,) = sales
    assert march["gain_native"] == 50.0  # en dólares, ganancia
    assert march["wash_sale_blocked"] is True
    assert march["blocked_loss_base"] == 55.0
    assert march["gain_base"] == 0.0  # pérdida en euros NO computable
    assert row["gain_base"] == 0.0


def test_la_perdida_diferida_en_euros_se_computa_al_vender_el_lote_recomprado(db):
    c = _setup(db)
    _tx(db, c, date(2025, 1, 10), "buy", 10, 100)
    _tx(db, c, date(2025, 3, 3), "sell", 10, 105)
    _tx(db, c, date(2025, 3, 20), "buy", 10, 104)
    _tx(db, c, date(2025, 7, 1), "sell", 10, 104)  # vende el lote recomprado
    _tx(db, c, date(2025, 12, 1), "buy", 1, 104)  # >2 meses después: no bloquea

    report = TaxReportService().compute_report(db, 2025)
    row, sales = _sales(report)
    march, july = sales
    assert march["gain_base"] == 0.0
    assert july["cost_base"] == 991.0  # 936 + 55 diferidos
    assert july["gain_base"] == -55.0
    assert row["gain_base"] == -55.0


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
