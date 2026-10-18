"""Dividendos declarados aparecen en /corporate-actions con fuente y fechas reales."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.corporate_actions import list_actions
from app.models import Company, DividendRecord, Position
from app.models.entities import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db, ticker):
    row = Company(ticker=ticker, name=ticker, exchange="NYSE", currency="USD", company_type="operating", valuation_model="unassigned")
    db.add(row)
    db.flush()
    return row


def test_declared_dividends_of_open_positions_listed_with_source_and_dates(db):
    held, other, sold = _company(db, "HLD"), _company(db, "OTH"), _company(db, "SLD")
    today = date.today()
    for comp, qty in ((held, "3"), (sold, "0")):
        db.add(Position(tenant_id=1, company_id=comp.id, quantity=Decimal(qty), average_cost=Decimal("10"), currency="USD", as_of=today, market_value=Decimal("30")))
    for comp, ex in ((held, today + timedelta(days=10)), (held, today - timedelta(days=30)), (held, today - timedelta(days=400)), (other, today), (sold, today)):
        db.add(DividendRecord(tenant_id=1, company_id=comp.id, ex_date=ex, pay_date=ex + timedelta(days=14), amount=Decimal("0.5300000000"), currency="USD", source="yahoo_finance"))
    db.commit()
    rows = list_actions(limit=200, db=db)
    assert [r["ticker"] for r in rows] == ["HLD", "HLD"]
    first = rows[0]
    assert first["action_type"] == "dividend" and first["declared"] is True and first["id"] is None
    assert first["effective_date"] == (today + timedelta(days=10)).isoformat()
    assert "0.53 USD por acción" in first["description"] and "fuente yahoo_finance" in first["description"]
    assert f"pago {(today + timedelta(days=24)).isoformat()}" in first["description"]
    assert first["applied"] is None
    assert first["amount_per_share"] == 0.53 and first["currency"] == "USD"
    assert first["pay_date"] == (today + timedelta(days=24)).isoformat()


def test_no_dividends_means_no_rows(db):
    assert list_actions(limit=200, db=db) == []


def test_daily_dividend_sync_is_scheduled():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "workers" / "scheduler.py").read_text()
    assert 'job_id="portfolio_dividends_daily"' in src and "sync_portfolio_dividends" in src


def test_sync_status_reports_last_real_import_or_none(db):
    from datetime import UTC, datetime

    from app.api.routes.corporate_actions import sync_status

    assert sync_status(db=db) == {"dividends_last_import": None, "splits_last_import": None}
    comp = _company(db, "HLD")
    stamp = datetime(2026, 10, 10, 6, 20, tzinfo=UTC)
    db.add(DividendRecord(tenant_id=1, company_id=comp.id, ex_date=date(2026, 10, 1), amount=Decimal("1"), currency="USD", source="yahoo_finance", fetched_at=stamp))
    db.commit()
    status = sync_status(db=db)
    assert status["dividends_last_import"].startswith("2026-10-10") and status["splits_last_import"] is None
