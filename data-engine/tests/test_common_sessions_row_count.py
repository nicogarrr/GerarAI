"""Count rows only where the company/date uniqueness invariant guarantees parity."""
import os
import random
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.models import Company, MarketPrice
from app.services import market_change as mc
from tests.test_market_change_latest_by_index import _capture, _close, _company


@pytest.fixture
def db():
    url = os.environ.get('COMMON_SESSIONS_TEST_PG_URL')
    raw = create_engine(url or 'sqlite:///:memory:')
    schema = 'sessions_test_' + uuid4().hex
    if url:
        with raw.begin() as conn:
            conn.execute(CreateSchema(schema))
        engine = raw.execution_options(schema_translate_map={None: schema})
    else:
        engine = raw
    try:
        Company.__table__.create(engine)
        MarketPrice.__table__.create(engine)
        with Session(engine) as session:
            yield session
    finally:
        if url:
            with raw.begin() as conn:
                conn.execute(DropSchema(schema, cascade=True))
        raw.dispose()


def old_sessions(db):
    rows = db.execute(select(MarketPrice.date, func.count(func.distinct(MarketPrice.company_id)))
        .where(MarketPrice.source.in_(mc.OFFICIAL_CLOSE_SOURCES), MarketPrice.date <= date.today())
        .group_by(MarketPrice.date).order_by(MarketPrice.date.desc()).limit(30)).all()
    days = [(day, n) for day, n in rows if day.weekday() < 5][:10]
    if not days:
        return None, None
    counts = sorted(n for _, n in days)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid-1] + counts[mid]) / 2
    result = [day for day, n in days if n >= median/2]
    return (result[0] if result else None, result[1] if len(result) > 1 else None)


@pytest.mark.parametrize('seed', range(10))
def test_row_count_matches_old_distinct_with_gaps_sources_weekends_future(db, seed):
    rng = random.Random(seed)
    companies = [_company(db, f'C{i}') for i in range(12)]
    for offset in range(-5, 70):
        for company in companies:
            if rng.random() < 0.6:
                _close(db, company, date.today()-timedelta(days=offset), '100',
                       'yfinance' if rng.random() < 0.7 else 'finnhub')
    db.commit()
    assert mc.common_sessions(db) == old_sessions(db)
    with _capture(db) as sql:
        mc.common_sessions(db)
    assert len(sql) == 1
    assert 'count(*)' in sql[0].lower()
    assert 'distinct' not in sql[0].lower()


def test_count_relies_on_enforced_unique_company_date(db):
    company = _company(db, 'UNIQUE')
    _close(db, company, date.today(), '100')
    db.commit()
    # A second source cannot introduce another company count on the same date.
    _close(db, company, date.today(), '101', 'finnhub')
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert not MarketPrice.__table__.c.company_id.nullable
    assert not MarketPrice.__table__.c.date.nullable
