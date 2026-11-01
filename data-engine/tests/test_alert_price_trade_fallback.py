"""Una alerta de precio no salta con el precio de tu propia operación.

Sin ninguna cotización guardada (MarketPrice), la alerta de precio miraba
``Position.market_price``. En una posición del ledger sin cotización ese
precio es el de la última compra/venta (auditoría A3, «sin cotización real»
en /positions): comprar hoy a 12,50 y crear «avísame si baja de 13» disparaba
al momento «valor observado: 12.5», como si el mercado hubiera bajado.
Un precio de broker (IBKR) en la posición sí es una cotización y sigue valiendo.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models.entities import Base, Company, Position
from app.services import alert_rule_service
from app.services.alert_rule_service import AlertRuleService
from app.services.portfolio_ledger_service import PortfolioLedgerService


@pytest.fixture(autouse=True)
def _cierre_al_dia(monkeypatch):
    # La frescura del cierre depende del reloj y del calendario de la bolsa;
    # aquí solo importa de dónde sale el precio.
    monkeypatch.setattr(alert_rule_service, "close_is_stale", lambda *args, **kwargs: False)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _buy(db: Session, ticker: str, price: str) -> Company:
    PortfolioLedgerService().create_transaction(
        db, ticker=ticker, action="buy", quantity=Decimal("4"), price=Decimal(price),
        trade_date=local_today() - timedelta(days=1), fees=Decimal("0"), currency="USD",
    )
    db.commit()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    assert company is not None
    return company


def test_precio_de_la_operacion_no_dispara_la_alerta(db: Session):
    company = _buy(db, "ZZALQ", "12.5")
    rule = AlertRuleService().create(db, company, rule_type="price_below", operator="<", value=13)

    result = AlertRuleService().evaluate(db, rule)

    assert result["status"] != "triggered"
    assert result["matched"] is False
    assert result["observation"]["status"] == "missing"


def test_precio_de_broker_en_la_posicion_si_dispara(db: Session):
    company = _buy(db, "ZZALB", "12.5")
    position = db.scalar(select(Position).where(Position.company_id == company.id))
    assert position is not None
    position.source = "ibkr_flex"
    position.market_price = Decimal("11")
    db.commit()
    rule = AlertRuleService().create(db, company, rule_type="price_below", operator="<", value=13)

    result = AlertRuleService().evaluate(db, rule)

    assert result["status"] == "triggered"
