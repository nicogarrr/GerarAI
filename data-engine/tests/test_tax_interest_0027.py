"""Intereses cobrados → casilla 0027; intereses de margen pagados → no deducibles.

Fuentes: art. 25.2 y 26.1.a Ley 35/2006 (BOE-A-2006-20764); Manual de ayuda
Renta 2025, apdo. 7.2.3.1 ("Intereses de cuentas y depósitos: en ningún caso
podrán computarse gastos deducibles").

Cálculo a mano (tipo = EUR por 1 USD = 0,90 todo el año):
  31/03/2025 interés cobrado   +20,00 $ → +18,00 €
  30/06/2025 interés cobrado   +30,00 $ → +27,00 €
  31/07/2025 interés de margen −40,00 $ → −36,00 € (NO deducible)
  Casilla 0027 = 18 + 27 = 45,00 €; margen pagado = 36,00 € (no resta).
  Dividendo 100 $ → 90,00 €. Saldo de rendimientos del ahorro = 90 + 45 =
  135,00 € → límite de compensación del 25 % = 33,75 € (antes 22,50 €, solo
  con dividendos).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Transaction
from app.services.tax_irpf_filing import build_interest
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _cash(db, company_id, day, action, amount):
    db.add(Transaction(
        company_id=company_id, trade_date=day, action=action,
        quantity=Decimal("1"), price=Decimal(str(amount)),
        fees=Decimal("0"), currency="USD",
    ))
    db.commit()


def test_build_interest_suma_cobrados_y_separa_margen_no_deducible():
    rows = [
        {"type": "interest", "amount_native": 20.0, "amount_base": 18.0, "currency": "USD", "date": "2025-03-31"},
        {"type": "interest", "amount_native": 30.0, "amount_base": 27.0, "currency": "USD", "date": "2025-06-30"},
        {"type": "interest", "amount_native": -40.0, "amount_base": -36.0, "currency": "USD", "date": "2025-07-31"},
        {"type": "fee", "amount_native": -10.0, "amount_base": -9.0, "currency": "USD", "date": "2025-08-01"},
    ]
    out = build_interest(rows, 2025)
    assert out["received"]["casilla"] == "0027"
    assert out["received"]["amount_base"] == 45.0
    assert out["margin_interest_paid"]["amount_base"] == 36.0
    assert out["margin_interest_paid"]["deductible"] is False
    assert out["incomplete"] is False


def test_build_interest_sin_fx_no_publica_total():
    rows = [
        {"type": "interest", "amount_native": 20.0, "amount_base": 18.0, "currency": "USD", "date": "2025-03-31"},
        {"type": "interest", "amount_native": 5.0, "amount_base": None, "currency": "JPY", "date": "2025-04-30"},
    ]
    out = build_interest(rows, 2025)
    assert out["received"]["amount_base"] is None
    assert out["received"]["status"] == "SIN_DATOS"
    assert len(out["manual_review"]) == 1


def test_informe_publica_intereses_y_los_suma_al_saldo_de_rendimientos(db):
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    company = Company(
        ticker="USX", name="USX", exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[], domicile_country="US",
    )
    db.add(company)
    db.add(FXRate(base_currency="EUR", quote_currency="USD",
                  rate_date=date(2025, 1, 1), rate=Decimal("0.90"), source="test"))
    db.commit()
    _cash(db, company.id, date(2025, 5, 2), "dividend", 100)
    _cash(db, None, date(2025, 3, 31), "interest", 20)
    _cash(db, None, date(2025, 6, 30), "interest", 30)
    _cash(db, None, date(2025, 7, 31), "interest", -40)

    report = TaxReportService().compute_report(db, 2025)
    filing = report["filing"]
    assert filing["intereses"]["received"]["amount_base"] == 45.0
    assert filing["intereses"]["margin_interest_paid"]["amount_base"] == 36.0
    comp = filing["loss_compensation"]
    assert comp["current_rcm_net_base"] == 135.0
    assert comp["cross_limit_base"] == 33.75
