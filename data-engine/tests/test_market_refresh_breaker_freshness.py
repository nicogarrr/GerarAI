"""Breaker abierto (429 en todos los proveedores): la corrida NO puede
presentarse como datos actualizados.

Con cero observaciones y errores provider_unavailable: no se escribe ningun
precio con la fecha del run, el stage de precios queda "partial" con 0
actualizados, la revaloracion declara "stale_data" y el riesgo marca
market_data_status "stale". La deteccion del breaker en si ya esta cubierta
en test_market_refresh_service (429 -> provider_unavailable, racha abre
breaker); aqui se fija el contrato de frescura del run completo.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import Base, Company, MarketPrice, Portfolio, Position
from app.services.market_refresh_service import (
    ECBRates,
    MarketRefreshService,
    PriceObservation,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session
    engine.dispose()


class _AllProvidersDown:
    async def fetch(self, companies, *, as_of):
        return {}, [
            {"ticker": company.ticker, "reason": "FMP:provider_unavailable,Finnhub:provider_unavailable"}
            for company in companies
        ]


class _FakeFXProvider:
    async def fetch(self, *, base_currency, quote_currencies):
        return ECBRates(rate_date=date(2026, 9, 22), rates={c: Decimal("1.1") for c in quote_currencies})


def _seed(db: Session, n: int) -> None:
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    for i in range(n):
        company = Company(
            ticker=f"T{i:02d}", name=f"T{i:02d}", exchange="NASDAQ", currency="USD",
            sector="S", industry="I", company_type="holding", valuation_model="unassigned",
            special_sources=[], special_risks=[], factor_tags=[],
        )
        db.add(company)
        db.flush()
        db.add(Position(company_id=company.id, quantity=Decimal("10"), currency="USD",
                        market_price=Decimal("90"), market_value=Decimal("900")))
        # Ultimo cierre hace 30 dias: cualquier politica de frescura lo declara stale.
        db.add(MarketPrice(company_id=company.id, date=date(2026, 8, 23), close=Decimal("95"),
                           adj_close=Decimal("95"), source="seed"))
    db.commit()


def test_breaker_open_run_writes_no_prices_and_marks_stale(db):
    _seed(db, 3)
    service = MarketRefreshService(price_provider=_AllProvidersDown(), fx_provider=_FakeFXProvider())
    result = asyncio.run(service.refresh(db, as_of=date(2026, 9, 22)))

    # El run no es "ok": nada se actualizo por culpa del breaker.
    assert result["status"] == "partial"
    prices_stage = result["stages"][0]
    assert prices_stage["name"] == "update_prices"
    assert prices_stage["status"] == "partial"
    assert prices_stage["updated"] == 0
    # Ningun precio escrito con la fecha del run: seria fabricar frescura.
    assert db.scalars(select(MarketPrice).where(MarketPrice.date == date(2026, 9, 22))).all() == []
    # La revaloracion y el riesgo declaran el dato viejo, no "actualizado".
    revalue_stage = next(s for s in result["stages"] if s["name"] == "revalue_positions")
    assert revalue_stage["status"] == "stale_data"
    assert {row["ticker"] for row in revalue_stage["stale_prices"]} == {"T00", "T01", "T02"}
    assert result["risk"]["market_data_status"] == "stale"
