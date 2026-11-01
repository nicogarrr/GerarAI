"""«Hoy» en la estimación de venta es el día de Madrid, no el día UTC del servidor.

Producción corre con TZ=UTC. Entre las 00:00 y la 01:00 (invierno) de Madrid,
``date.today()`` todavía es «ayer»: una compra registrada hoy quedaba fuera de
los lotes FIFO (la simulación caía al coste medio y perdía la regla de los dos
meses) y un lote hipotético comprado hoy se rechazaba como «fecha futura».
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Portfolio, Transaction

UTC_DAY = date(2026, 3, 10)          # día del reloj del servidor (UTC)
MADRID_DAY = date(2026, 3, 11)       # 00:30 en Madrid
NOW = datetime(2026, 3, 10, 23, 30, tzinfo=UTC)


class UtcClock(date):
    @classmethod
    def today(cls):
        return UTC_DAY


@pytest.fixture
def madrid_after_midnight(monkeypatch):
    import app.core.local_date as local_date
    import app.services.sale_hypothetical as hypo
    import app.services.sale_simulation as sim

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    monkeypatch.setattr(sim, "date", UtcClock)
    monkeypatch.setattr(hypo, "date", UtcClock)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        company = Company(ticker="TEST", name="Synthetic", exchange="XETRA", currency="EUR",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        db.flush()
        db.add(Portfolio(tenant_id=1, name="P", base_currency="EUR", is_default=True))
        db.flush()
        yield db, company
    engine.dispose()


def test_compra_de_hoy_entra_en_los_lotes_fifo(madrid_after_midnight):
    from app.services.sale_simulation import simulate_fifo_sale

    db, company = madrid_after_midnight
    for day, qty, price in [(date(2026, 1, 5), "10", "10"), (MADRID_DAY, "10", "12")]:
        db.add(Transaction(tenant_id=1, company_id=company.id, trade_date=day, action="buy",
                           quantity=D(qty), price=D(price), fees=D("0"), currency="EUR"))
    db.flush()
    sale = simulate_fifo_sale(db, tenant_id=1, company_id=company.id,
                              quantity=D(20), held_quantity=D(20))
    assert sale is not None
    assert sale.cost_eur == D(220)


def test_lote_hipotetico_comprado_hoy_no_es_fecha_futura(madrid_after_midnight):
    from app.services.sale_hypothetical import HypoLot, simulate_hypothetical_sale

    db, company = madrid_after_midnight
    res = simulate_hypothetical_sale(
        db,
        lots=[HypoLot(quantity=D(10), price=D(10), currency="EUR", trade_date=MADRID_DAY)],
        question="IRPF si vendo 10 acciones de TEST a 12 euros",
        company=company,
    )
    assert not res.invalid or "futura" not in res.invalid
