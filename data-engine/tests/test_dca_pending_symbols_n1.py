"""pending_symbols decide que tickers entran en la tanda DCA manual.

Antes hacia una consulta a market_prices por ticker seguido (N+1): con una
watchlist de 60 valores, 60 SELECT en la peticion POST
/dca-signals/evaluate-async. Ahora es un solo agregado, y el criterio de
"hay un cierre guardado mas nuevo que la evaluacion" no cambia.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DcaSignalState, MarketPrice, Tenant, WatchItem
from app.services.dca_manual import pending_symbols
from app.services.dca_signal_engine import DEFAULT_PARAMS

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t-pending", name="t"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _tracked(db, ticker: str, *, close_on: date | None, evaluated: datetime | None) -> None:
    company = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
        sector="x", industry="x", company_type="x", valuation_model="x",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    db.add(WatchItem(tenant_id=1, symbol=ticker))
    if close_on is not None:
        for days in (3, 0):
            db.add(MarketPrice(company_id=company.id, date=close_on - timedelta(days=days),
                               open=1, high=1, low=1, close=Decimal("10")))
    if evaluated is not None:
        db.add(DcaSignalState(
            tenant_id=1, symbol=ticker, company_id=company.id, level=1, status="ok",
            period="2026-10", signal_date=evaluated.date(), close=Decimal("10"),
            params_version=DEFAULT_PARAMS.version, evaluated_at=evaluated, data_source="test",
        ))
    db.commit()


def _market_price_selects(db, fn):
    seen: list[str] = []

    def before(conn, cursor, statement, params, context, executemany):
        if "market_prices" in statement.lower():
            seen.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return result, seen


def test_pending_symbols_reads_market_prices_once_not_per_ticker(db):
    fresh = NOW - timedelta(hours=2)
    # Cierre de hoy y evaluacion de ayer: hay un cierre mas nuevo -> pendiente.
    _tracked(db, "NEWCLOSE", close_on=NOW.date(), evaluated=NOW - timedelta(hours=21))
    # Evaluado tras el ultimo cierre guardado -> no pendiente.
    for i in range(6):
        _tracked(db, f"FRESH{i}", close_on=NOW.date() - timedelta(days=1), evaluated=fresh)
    # Sin estado -> pendiente; sin precios no rompe.
    _tracked(db, "NOSTATE", close_on=None, evaluated=None)

    pending, selects = _market_price_selects(db, lambda: pending_symbols(db, now=NOW))

    assert pending == ["NEWCLOSE", "NOSTATE"]
    assert len(selects) <= 1, f"{len(selects)} consultas a market_prices (N+1)"
