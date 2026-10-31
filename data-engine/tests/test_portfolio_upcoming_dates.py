"""«Próximas fechas» de la cartera (idea Jera Value): resultados oficiales o estimados,
ex-dividendo y pago desde tablas guardadas, y un recordatorio el día antes en el feed."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, DividendRecord, EarningsDate, Portfolio, Position
from app.services.calendar_feed_service import build_ics
from app.services.earnings_dates_service import (
    followed_calendar,
    portfolio_dividend_dates,
    portfolio_upcoming,
)

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.flush()
    return db


def _held(db: Session, ticker: str) -> Company:
    company = Company(ticker=ticker, name=f"{ticker} SA", exchange="BME", currency="EUR", sector="T", industry="T",
                      company_type="stock", valuation_model="dcf", special_sources=[], special_risks=[], factor_tags=[])
    db.add(company)
    db.flush()
    db.add(Position(company_id=company.id, portfolio_id=1, quantity=Decimal("10"), average_cost=Decimal("10"),
                    currency="EUR", base_currency="EUR", source="probe"))
    return company


def _seed(db: Session) -> None:
    ite = _held(db, "ITX")
    _held(db, "SAN")
    db.add(EarningsDate(ticker="ITX", event_date=date(2026, 11, 20), confirmed=True, source="manual",
                        source_label="Inditex (web oficial)", source_url="https://www.inditex.com/x", fetched_at=NOW))
    db.add(EarningsDate(ticker="SAN", event_date=date(2026, 11, 25), confirmed=False, source="manual",
                        source_label="Estimación NASDAQ", fetched_at=NOW))
    db.add(DividendRecord(company_id=ite.id, ex_date=date(2026, 11, 2), pay_date=date(2026, 11, 4),
                          amount=Decimal("0.77"), currency="EUR", source="fmp"))
    db.add(DividendRecord(company_id=ite.id, ex_date=date(2026, 5, 2), pay_date=date(2026, 5, 4),
                          amount=Decimal("0.7"), currency="EUR", source="fmp"))
    db.commit()


def test_portfolio_upcoming_lists_results_and_dividends_with_status_and_reminder():
    with _db() as db:
        _seed(db)
        out = portfolio_upcoming(db, date(2026, 10, 31), date(2027, 1, 31), now=NOW)
    rows = [(i["date"], i["ticker"], i["kind"], i["status"], i["reminder"]) for i in out["items"]]
    assert rows == [
        ("2026-11-02", "ITX", "ex_dividend", "oficial", "2026-11-01"),
        ("2026-11-04", "ITX", "dividend_payment", "oficial", "2026-11-03"),
        ("2026-11-20", "ITX", "results", "oficial", "2026-11-19"),
        ("2026-11-25", "SAN", "results", "estimada", "2026-11-24"),
    ]
    assert all(i["source"] for i in out["items"])
    assert any("Juntas" in line for line in out["limitations"])


def test_feed_has_one_reminder_per_event_and_includes_dividends():
    with _db() as db:
        _seed(db)
        calendar = followed_calendar(db, date(2026, 10, 31), date(2027, 1, 31), now=NOW)
        dividends = portfolio_dividend_dates(db, date(2026, 10, 31), date(2027, 1, 31))
    ics = build_ics(calendar, now=NOW, dividends=dividends)
    events = ics.split("BEGIN:VEVENT")[1:]
    assert len(events) == 4
    for block in events:
        assert block.count("BEGIN:VALARM") == 1 and "TRIGGER:-P1D" in block
        assert block.index("END:VALARM") < block.index("END:VEVENT")
    assert "ITX SA (ITX): ex-dividendo" in ics and "pago de dividendo" in ics
    assert "Mañana: SAN SA (SAN): resultados (fecha estimada)" in ics
