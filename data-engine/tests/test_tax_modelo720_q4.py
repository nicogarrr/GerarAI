"""Modelo 720 — saldo medio del 4.º trimestre de las cuentas.

Norma: art. 42 bis.4.b RD 1065/2007 y Orden HAP/72/2013: de cada cuenta se
informa el saldo a 31/12 y el saldo medio del último trimestre, y basta que
UNO de los dos supere 50.000 € (FAQ AEAT del 720, «Forma de calcular el
límite»). FAQ AEAT «Valoración»: ambos se convierten al tipo de cambio
vigente a 31/12.

Cálculo a mano (saldo medio = media de los 92 saldos diarios 1/10–31/12):
  70.000 $ del 1/10 al 30/11 (61 días) y 30.000 $ del 1/12 al 31/12 (31 días)
  → (70.000×61 + 30.000×31) / 92 = 5.200.000 / 92 = 56.521,74 $
  → al tipo del 31/12 (0,90 €/$) = 50.869,57 € > 50.000 €
  mientras que el saldo a 31/12 es 30.000 $ × 0,90 = 27.000 € (< 50.000 €).
  Antes, sin saldo medio, la categoría nunca podía salir «por debajo» y el
  caso de arriba no se detectaba.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashBalance, CashDailySnapshot, Portfolio, PortfolioDailySnapshot, Tenant
from app.services.tax_modelo720_service import Modelo720Service, q4_average_native


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db):
    tenant = Tenant(external_id="m720-q4", name="Q4")
    db.add(tenant)
    db.flush()
    tenant.metadata_ = {"tax_declarant": {"custody": {"cash:USD": "IE"}}}
    portfolio = Portfolio(tenant_id=tenant.id, name="Main", base_currency="EUR", is_default=True)
    db.add(portfolio)
    db.flush()
    db.add(CashBalance(tenant_id=tenant.id, currency="USD", balance=Decimal("0"), source="ibkr_flex"))
    db.flush()
    return tenant, portfolio


def _snap(db, tenant, portfolio, day, balance, fx="0.90"):
    parent = PortfolioDailySnapshot(
        tenant_id=tenant.id, portfolio_id=portfolio.id, snapshot_date=day,
        base_currency="EUR", positions_value_base=Decimal("0"),
        cash_value_base=Decimal("0"), total_value_base=Decimal("0"),
        metadata_={"missing_pricing": []},
    )
    db.add(parent)
    db.flush()
    db.add(CashDailySnapshot(
        tenant_id=tenant.id, portfolio_snapshot_id=parent.id, portfolio_id=portfolio.id,
        snapshot_date=day, currency="USD", balance_native=Decimal(str(balance)),
        fx_rate=Decimal(fx),
    ))
    db.flush()


def _weekly(start, end):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=7)


def test_q4_average_media_diaria_con_arrastre():
    points = [(d, Decimal("70000")) for d in _weekly(date(2025, 10, 1), date(2025, 11, 30))]
    points += [(d, Decimal("30000")) for d in _weekly(date(2025, 12, 1), date(2025, 12, 31))]
    points.append((date(2025, 12, 31), Decimal("30000")))
    avg = q4_average_native(points, 2025)
    assert avg is not None
    assert avg.quantize(Decimal("0.01")) == Decimal("56521.74")


def test_q4_average_sin_cobertura_semanal_no_se_inventa():
    points = [(date(2025, 10, 1), Decimal("1000")), (date(2025, 10, 20), Decimal("1000")),
              (date(2025, 12, 31), Decimal("1000"))]
    assert q4_average_native(points, 2025) is None


def test_720_cuentas_saldo_medio_4t_supera_aunque_31_12_no(db):
    tenant, portfolio = _seed(db)
    for d in _weekly(date(2025, 10, 1), date(2025, 11, 30)):
        _snap(db, tenant, portfolio, d, 70000)
    for d in _weekly(date(2025, 12, 1), date(2025, 12, 29)):
        _snap(db, tenant, portfolio, d, 30000)
    _snap(db, tenant, portfolio, date(2025, 12, 31), 30000)

    cuentas = Modelo720Service().check_thresholds(db, 2025)["categories"]["cuentas"]
    assert cuentas["total_base"] == 27000.0
    assert cuentas["average_q4_missing"] is False
    assert cuentas["average_q4_total_base"] == 50869.57
    # Supera por saldo medio; sigue «no concluyente» porque los saldos van por
    # divisa y no por cuenta real (regla previa), pero ya NO puede salir
    # «por debajo».
    assert cuentas["status"] != "por_debajo"
    assert cuentas["balances"][0]["average_q4_base"] == 50869.57


def test_720_cuentas_por_debajo_con_saldo_medio_conocido(db):
    tenant, portfolio = _seed(db)
    for d in _weekly(date(2025, 10, 1), date(2025, 12, 31)):  # incluye el 31/12
        _snap(db, tenant, portfolio, d, 20000)

    cuentas = Modelo720Service().check_thresholds(db, 2025)["categories"]["cuentas"]
    assert cuentas["total_base"] == 18000.0
    assert cuentas["average_q4_total_base"] == 18000.0
    assert cuentas["status"] == "por_debajo"
    assert cuentas["exceeds"] is False
