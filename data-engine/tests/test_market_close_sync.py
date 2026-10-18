"""market_close_sync: barras oficiales, sin la sesion en curso."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, MarketPrice
from app.services.market_close_sync import sync_official_closes
from app.services.propicks_price_service import PriceBar


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _bars():
    return {
        "AAPL": [
            PriceBar(date(2026, 10, 15), Decimal("342.00"), Decimal("342.00"), 10),
            PriceBar(date(2026, 10, 16), Decimal("343.46"), Decimal("343.46"), 11),
        ]
    }


def _company(db):
    db.add(
        Company(
            ticker="AAPL", name="AAPL", exchange="NASDAQ", currency="USD", sector="S",
            industry="I", company_type="holding", valuation_model="unassigned",
            special_sources=[], special_risks=[], factor_tags=[],
        )
    )
    db.flush()


def test_writes_official_bars_after_close(db):
    _company(db)
    now = datetime(2026, 10, 16, 22, 30, tzinfo=UTC)  # 18:30 Nueva York
    out = sync_official_closes(db, fetcher=lambda symbols, period: _bars(), now=now)
    rows = db.scalars(select(MarketPrice).order_by(MarketPrice.date)).all()
    assert out["bars_written"] == 2 and out["partial_session_skipped"] is False
    assert [r.source for r in rows] == ["yfinance", "yfinance"]


def test_skips_session_in_progress(db):
    _company(db)
    now = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)  # 11:00 Nueva York, sesion abierta
    out = sync_official_closes(db, fetcher=lambda symbols, period: _bars(), now=now)
    rows = db.scalars(select(MarketPrice)).all()
    assert out["partial_session_skipped"] is True
    assert [r.date for r in rows] == [date(2026, 10, 15)]
