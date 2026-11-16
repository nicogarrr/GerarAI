"""Prove SQL caps bound ORM loads, not merely SQL statement count."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, MarketPrice, NewsEvent, Portfolio, Position
from app.services.portfolio_moves_service import build_digest


@pytest.mark.parametrize('size', [1, 20, 60])
def test_digest_caps_history_before_orm_materialization(size):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            seed.info['tenant_id'] = 'moves-budget'
            fund = Portfolio(name='Main', tenant_id='moves-budget')
            seed.add(fund)
            seed.flush()
            for index in range(size):
                company = Company(ticker=f'MV{index:03}', name='Fixture', exchange='NASDAQ', currency='USD',
                                  company_type='holding', valuation_model='unassigned')
                seed.add(company)
                seed.flush()
                seed.add(Position(company_id=company.id, portfolio_id=fund.id, quantity=Decimal('2'), tenant_id='moves-budget'))
                for offset in range(9):
                    seed.add(MarketPrice(company_id=company.id, date=date(2026, 9, 24)-timedelta(days=offset),
                                         close=Decimal(20-offset), adj_close=Decimal(20-offset), source='yfinance'))
                for minute in range(40):
                    seed.add(NewsEvent(company_id=company.id, tenant_id='moves-budget',
                                       date=datetime(2026, 9, 24, 8, minute, tzinfo=UTC), title=f'News {minute}',
                                       source='example.com', url=f'https://example.com/{index}/{minute}',
                                       metadata_={'connector':'gdelt'}))
            seed.commit()
            # More recent foreign-tenant articles must be filtered before rank.
            seed.info['tenant_id'] = 'foreign'
            for minute in range(40, 50):
                seed.add(NewsEvent(company_id=company.id, tenant_id='foreign',
                                   date=datetime(2026, 9, 24, 8, minute, tzinfo=UTC), title='PRIVATE',
                                   source='foreign.invalid', url=f'https://foreign.invalid/{minute}',
                                   metadata_={'connector':'gdelt'}))
            seed.commit()
        loaded = {'MarketPrice': 0, 'NewsEvent': 0}
        statements = []
        def count_load(_session, instance):
            kind = type(instance).__name__
            if kind in loaded:
                loaded[kind] += 1
        def count_sql(_conn, _cursor, statement, *_args):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', count_sql)
        with Session(engine, expire_on_commit=False) as db:
            db.info['tenant_id'] = 'moves-budget'
            event.listen(db, 'loaded_as_persistent', count_load)
            digest = build_digest(db, date(2026, 9, 24), datetime(2026, 9, 25, tzinfo=UTC))
            assert len(digest.items) == size
            assert all(item['status'] == 'disponible' for item in digest.items)
            assert all(item['adjusted_close'] == '20.000000' and item['previous_adjusted_close'] == '19.000000' for item in digest.items)
            assert all([news['title'] for news in item['related_news']] == [f'News {n}' for n in range(39, 34, -1)] for item in digest.items)
        print(f'size={size} statements={len(statements)} ORM={loaded}')
        assert len(statements) <= 8
        assert loaded == {'MarketPrice': 2*size, 'NewsEvent': 5*size}
    finally:
        engine.dispose()
