"""Job del radar: universo acotado, resumible, honesto con unidad y ajuste."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, MarketPrice, ProPicksRadarSnapshot
from app.services.propicks_radar_job import run_radar_scan, universe_company_ids

AS_OF = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)


def _company(db: Session, cid: int, ticker: str) -> None:
    db.add(Company(id=cid, ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ",
                   currency="USD", sector="Technology", industry="Test",
                   company_type="large_cap", valuation_model="dcf"))


def _bars(db: Session, cid: int, *, months: int = 30, adj: bool = True,
          currency: str | None = "USD", declining: bool = True) -> None:
    """~21 sesiones por mes terminando el día anterior a AS_OF (asentadas)."""
    end = AS_OF - timedelta(days=1)
    days = months * 21
    price = 200.0
    for i in range(days):
        day = end - timedelta(days=days - 1 - i)
        price *= 0.998 if declining else 1.001
        db.add(MarketPrice(company_id=cid, date=day, open=price, high=price,
                           low=price, close=price,
                           adj_close=price if adj else None,
                           volume=1_000_000, quote_currency=currency, source="test"))


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_scan_persists_snapshots_and_resumes_without_duplicates(db):
    _company(db, 1, "AAA")
    _company(db, 2, "BBB")
    _bars(db, 1)
    _bars(db, 2, declining=False)
    db.commit()
    assert universe_company_ids(db) == [1, 2]

    first = run_radar_scan(db, as_of=AS_OF, now=NOW)
    assert first["status"] == "completed"
    assert first["saved"] == 2
    assert first["universe"] == 2
    rows = db.scalars(select(ProPicksRadarSnapshot)).all()
    assert len(rows) == 2
    by_company = {r.company_id: r for r in rows}
    assert by_company[1].status == "ok"
    assert by_company[1].payload["formula_version"] == "nico-v1"
    assert by_company[1].payload["current"]["status"] == "forming"
    assert by_company[1].payload["confirmed"] is not None

    # Reejecutar el mismo día no duplica ni infla cobertura (idempotente).
    second = run_radar_scan(db, as_of=AS_OF, now=NOW)
    assert second["saved"] == 0
    assert len(db.scalars(select(ProPicksRadarSnapshot)).all()) == 2


def test_missing_adjusted_series_and_unknown_unit_are_invalid_not_invented(db):
    _company(db, 1, "NOADJ")
    _company(db, 2, "NOCCY")
    _bars(db, 1, adj=False)          # adj_close NULL: serie no verificada
    _bars(db, 2, currency=None)      # unidad legada desconocida
    db.commit()
    run_radar_scan(db, as_of=AS_OF, now=NOW)
    rows = {r.company_id: r for r in db.scalars(select(ProPicksRadarSnapshot)).all()}
    assert rows[1].status == "invalid"
    assert rows[1].payload["reason"] == "unverified_adjusted_series"
    assert rows[2].status == "invalid"
    assert rows[2].payload["reason"] == "currency_mismatch"


def test_today_session_never_enters_the_scan(db):
    _company(db, 1, "AAA")
    _bars(db, 1)
    # Fila de HOY (posible spot intradía): no puede entrar en la señal.
    db.add(MarketPrice(company_id=1, date=AS_OF, open=1, high=1, low=1, close=1,
                       adj_close=1, volume=1, quote_currency="USD", source="test"))
    db.commit()
    run_radar_scan(db, as_of=AS_OF, now=NOW)
    row = db.scalar(select(ProPicksRadarSnapshot))
    assert row.status == "ok"
    assert row.payload["price_date"] == (AS_OF - timedelta(days=1)).isoformat()


def test_time_budget_stops_and_cursor_resumes_next_batch(db):
    for cid in range(1, 6):
        _company(db, cid, f"T{cid}")
        _bars(db, cid, months=13)
    db.commit()
    from app.services.propicks_radar_batch import ScanBudget

    # Presupuesto de 1 empresa por lote: el cursor avanza y el siguiente
    # lote continúa donde quedó, sin repetir ni saltarse empresas.
    budget = ScanBudget(max_companies=1, max_seconds=1800, min_request_interval=1)
    seen = []
    for _ in range(5):
        result = run_radar_scan(db, as_of=AS_OF, now=NOW, budget=budget)
        seen.append(result["cursor"])
    assert seen == [1, 2, 3, 4, 5]
    assert len(db.scalars(select(ProPicksRadarSnapshot)).all()) == 5
