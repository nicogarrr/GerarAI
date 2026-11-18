"""El refresco sin as_of usa el dia de Madrid, no el dia UTC del servidor.

Prod corre TZ=UTC: entre las 00:00 y la 01:00/02:00 de Madrid date.today()
aun es ayer. El refresco horario (refresh_market_pipeline, sin as_of) pedia
precios de ayer, fechaba la foto de cartera con ayer (pisando el cierre de
ayer) y evaluaba la caducidad con la rama de "hoy" equivocada.

Run from data-engine/:
    pytest tests/test_market_refresh_fecha_madrid.py -v
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.core.local_date as local_date
import app.services.market_refresh_service as mrs
import app.services.price_freshness as price_freshness
from app.models import PortfolioDailySnapshot
from app.models.entities import Base
from app.services.connectors.ecb import ECBRates
from app.services.market_refresh_service import MarketRefreshService, PriceObservation
from app.services.portfolio_ledger_service import PortfolioLedgerService

MADRID_DAY = date(2026, 11, 18)
UTC_DAY = MADRID_DAY - timedelta(days=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.fixture
def clock_23_30_utc(monkeypatch):
    """17-nov 23:30 UTC = 18-nov 00:30 Madrid; date.today() del servidor = 17-nov."""
    monkeypatch.setattr(local_date, "_utc_now", lambda: datetime(2026, 11, 17, 23, 30, tzinfo=UTC))

    class _UtcDate(date):
        @classmethod
        def today(cls):
            return UTC_DAY

    monkeypatch.setattr(price_freshness, "_now", lambda: datetime(2026, 11, 17, 23, 30, tzinfo=UTC))
    monkeypatch.setattr(mrs, "date", _UtcDate)
    monkeypatch.setattr("app.services.portfolio_snapshot_service.date", _UtcDate)


def _setup(db):
    ledger = PortfolioLedgerService()
    ledger.create_transaction(db, ticker="AAPL", action="buy", quantity=Decimal("10"),
                              price=Decimal("100"), currency="USD", trade_date=UTC_DAY)
    ledger.ensure_company(db, "AAPL").exchange = "NASDAQ"
    db.commit()


def _service(asked):
    class Prices:
        async def fetch(self, companies, *, as_of):
            asked.append(as_of)
            return {c.ticker: PriceObservation(c.ticker, Decimal("110"), as_of, "test") for c in companies}, []

    class FX:
        async def fetch(self, **kwargs):
            return ECBRates(rate_date=MADRID_DAY, rates={"USD": Decimal("1.1")})

    return MarketRefreshService(Prices(), FX())


def test_refresh_sin_as_of_pide_precios_y_fotografia_el_dia_de_madrid(db, clock_23_30_utc):
    _setup(db)
    asked = []

    result = asyncio.run(_service(asked).refresh(db))

    assert asked == [MADRID_DAY]
    assert result["as_of"] == MADRID_DAY
    dates = [s.snapshot_date for s in db.scalars(select(PortfolioDailySnapshot)).all()]
    assert dates == [MADRID_DAY]  # nunca la foto de ayer pisada


def test_refresh_con_as_of_explicito_lo_respeta(db, clock_23_30_utc):
    _setup(db)
    asked = []

    result = asyncio.run(_service(asked).refresh(db, as_of=UTC_DAY))

    assert asked == [UTC_DAY]
    assert result["as_of"] == UTC_DAY


def test_caducidad_de_hoy_usa_la_rama_de_cierre_de_la_bolsa_en_dia_de_madrid(db, clock_23_30_utc):
    """00:30 de Madrid: el cierre de NY de ayer (21:00Z) tiene 2,5 h, sigue vigente.

    Con la rama de dias naturales (as_of != hoy) ese mismo precio saldria caducado.
    """
    _setup(db)
    asked = []

    class Prices:
        async def fetch(self, companies, *, as_of):
            asked.append(as_of)
            return {c.ticker: PriceObservation(c.ticker, Decimal("110"), UTC_DAY, "test") for c in companies}, []

    class FX:
        async def fetch(self, **kwargs):
            return ECBRates(rate_date=MADRID_DAY, rates={"USD": Decimal("1.1")})

    result = asyncio.run(MarketRefreshService(Prices(), FX()).refresh(db))

    assert asked == [MADRID_DAY]
    assert result["stages"][2]["stale_prices"] == []
