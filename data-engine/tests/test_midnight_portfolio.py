"""«Hoy» de la cartera es el día de Madrid, no el día UTC del servidor.

Producción corre con TZ=UTC. A las 00:30 de Madrid (23:30 UTC) el reloj UTC
todavía marca «ayer»: una caja negativa registrada hoy se tomaba por «futura»
y no avisaba, y una valoración retenida hoy quedaba fechada ayer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import CashBalance, ResearchAlert
from app.models.entities import Base, Company, Portfolio, Position

NOW = datetime(2026, 3, 15, 23, 30, tzinfo=UTC)  # 00:30 del 16 de marzo en Madrid
UTC_DAY = date(2026, 3, 15)
MADRID_DAY = date(2026, 3, 16)


class UtcClock(date):
    @classmethod
    def today(cls):
        return UTC_DAY


@pytest.fixture
def db(monkeypatch):
    import app.core.local_date as local_date

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_caja_negativa_de_hoy_avisa_aunque_en_utc_sea_ayer(db, monkeypatch):
    import app.services.portfolio_proactivity as proactivity

    monkeypatch.setattr(proactivity, "date", UtcClock, raising=False)
    db.add(CashBalance(tenant_id=1, currency="EUR", balance=-100, source="manual", as_of=MADRID_DAY))
    db.commit()

    assert proactivity.review_portfolio_data(db)["new_in_app_alerts"] == 1
    alert = db.scalars(select(ResearchAlert)).one()
    assert MADRID_DAY.isoformat() in alert.message


def test_valoracion_retenida_hoy_queda_fechada_en_madrid(db, monkeypatch):
    import app.services.portfolio_ledger_service as ledger

    monkeypatch.setattr(ledger, "date", UtcClock)
    company = Company(ticker="DEMO", name="Demo", exchange="XETRA", currency="EUR",
                      company_type="holding", valuation_model="unassigned")
    portfolio = Portfolio(tenant_id=1, name="p", base_currency="EUR")
    db.add_all([company, portfolio])
    db.flush()
    position = Position(tenant_id=1, portfolio_id=portfolio.id, company_id=company.id,
                        quantity=Decimal("10"), average_cost=Decimal("10"), currency="EUR")
    db.add(position)
    db.flush()

    ledger.PortfolioLedgerService().hold_valuation(
        db, position, reason="split pendiente", effective_date=MADRID_DAY,
    )

    assert position.valuation_hold_since == MADRID_DAY
