"""Related-news strips must not expose future closes even if sessions are valid."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice
from app.services import news_related_tickers as service


def test_future_close_does_not_replace_observed_news_quote(monkeypatch):
    today = datetime.now(UTC).date()
    prior, future = today - timedelta(days=1), today + timedelta(days=1)
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(ticker='ABC', name='Example', currency='USD', exchange='NASDAQ',
                          company_type='holding', valuation_model='unassigned')
        db.add(company)
        db.flush()
        for day, close in [(prior, 100), (today, 110), (future, 999)]:
            db.add(MarketPrice(company_id=company.id, date=day, close=close,
                               source='yfinance', quote_currency='USD'))
        db.flush()
        monkeypatch.setattr(service, 'common_sessions', lambda _: (today, prior))
        quote = service.quotes_for(db, {company.id})[company.id]
        assert quote['date'] == today.isoformat()
        assert quote['price'] == 110
        assert quote['change_pct'] == 10
    engine.dispose()
