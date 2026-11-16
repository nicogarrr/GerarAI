"""Cold-session snapshot query budget; never time or cache-hit dependent."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import Company, Portfolio, Position
from app.models.entities import Base
from app.services.portfolio_quality_service import portfolio_quality
from app.services.portfolio_fx_service import PortfolioFXService


@pytest.mark.parametrize('size', [0, 1, 20, 60])
def test_quality_ibkr_company_reads_are_constant(size, monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as seed:
            seed.info['tenant_id'] = 'snapshot-budget'
            fund = Portfolio(name='Main', base_currency='EUR', tenant_id='snapshot-budget')
            foreign = Portfolio(name='Foreign', base_currency='EUR', tenant_id='snapshot-budget')
            seed.add_all([fund, foreign])
            seed.flush()
            fund_id, foreign_id = fund.id, foreign.id
            for index in range(size + 1):
                company = Company(ticker=f'BUD{index:03}', name='Fixture', exchange='X', currency='EUR',company_type='holding',valuation_model='unassigned')
                seed.add(company)
                seed.flush()
                seed.add(Position(portfolio_id=fund_id if index < size else foreign_id,
                                  company_id=company.id, quantity=Decimal('2.5'), market_price=Decimal('12'),
                                  currency='EUR', source='ibkr_flex', as_of=date(2026, 11, 16),
                                  tenant_id='snapshot-budget'))
            seed.commit()
        # Deliberately do not reuse seed's identity map, which masks lazy loads.
        queries = []
        loaded = {'Position': 0, 'Company': 0}
        def count_sql(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith('SELECT'):
                queries.append(statement)
        def count_load(_session, instance):
            key = type(instance).__name__
            if key in loaded:
                loaded[key] += 1
        event.listen(engine, 'before_cursor_execute', count_sql)
        with Session(engine) as db:
            db.info['tenant_id'] = 'snapshot-budget'
            event.listen(db, 'loaded_as_persistent', count_load)
            # Same fixed portfolio lookup both sides; isolates snapshot reads.
            monkeypatch.setattr(PortfolioFXService, 'portfolio',
                                lambda self, session: SimpleNamespace(id=fund_id, base_currency='EUR'))
            result = portfolio_quality(db)
        print(f'size={size} queries={len(queries)} ORM={loaded}')
        assert result['positions'] == size
        assert result['cost_unverified_positions'] == size
        assert result['missing_cost_positions'] == size
        assert result['position_sources'] == (['ibkr_flex'] if size else [])
        assert result['position_dates'] == (['2026-11-16'] if size else [])
        assert len(queries) == (3 if size == 0 else 5)
        assert loaded == {'Position': size, 'Company': size}
    finally:
        engine.dispose()
