"""«Hoy» de dividendos y calendario es el día de Madrid, no el día UTC del servidor.

Producción corre con TZ=UTC. A las 00:30 de Madrid del 1 de noviembre el reloj
UTC todavía marca el 31 de octubre: la proyección de dividendos empezaba en
octubre y el calendario macro arrancaba «ayer».
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, FXRate, Portfolio, Position

NOW = datetime(2026, 10, 31, 23, 30, tzinfo=UTC)  # 00:30 del 1 de noviembre en Madrid
UTC_DAY = date(2026, 10, 31)
MADRID_DAY = date(2026, 11, 1)


class UtcClock(date):
    @classmethod
    def today(cls):
        return UTC_DAY


@pytest.fixture
def madrid_after_midnight(monkeypatch):
    import app.core.local_date as local_date

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    return monkeypatch


def test_proyeccion_de_dividendos_empieza_en_el_mes_de_madrid(madrid_after_midnight):
    import app.services.dividend_projection_service as projection

    madrid_after_midnight.setattr(projection, "date", UtcClock)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker="DEMO", name="Demo", exchange="NASDAQ", currency="USD",
                          company_type="holding", valuation_model="unassigned")
        db.add(company)
        portfolio = Portfolio(name="p", base_currency="EUR")
        db.add(portfolio)
        db.flush()
        db.add(Position(portfolio_id=portfolio.id, company_id=company.id, quantity=Decimal("10"),
                        average_cost=Decimal("150"), market_price=Decimal("200"),
                        market_value=Decimal("2000"), currency="USD"))
        for days_ago in (15, 105, 195, 285):
            db.add(DividendRecord(company_id=company.id, ex_date=MADRID_DAY - timedelta(days=days_ago),
                                  amount=Decimal("0.25"), currency="USD", source="yahoo"))
        db.add(FXRate(base_currency="EUR", quote_currency="USD", rate_date=UTC_DAY, rate=Decimal("0.9")))
        db.commit()

        out = projection.DividendProjectionService().project(db, months=12)
    engine.dispose()

    assert out["months"][0]["month"] == "2026-11"
    assert all(m["month"] != "2026-10" for m in out["months"])


def test_calendario_macro_por_defecto_empieza_hoy_en_madrid(madrid_after_midnight):
    import app.api.routes.macro_calendar as route

    seen: dict[str, date] = {}

    async def fake_events(start, end):
        seen["start"], seen["end"] = start, end
        return {"status": "ok", "events": [], "errors": []}

    madrid_after_midnight.setattr(route, "date", UtcClock)
    madrid_after_midnight.setattr(route.macro_calendar_service, "get_macro_events", fake_events)

    asyncio.run(route.macro_events(desde=None, hasta=None, page=1, page_size=15))

    assert seen["start"] == MADRID_DAY
    assert seen["end"] == MADRID_DAY + timedelta(days=60)
