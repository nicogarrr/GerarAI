"""The public namespace cannot expose private rows or future filings."""
import importlib.util
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, FinancialFact
from app.models.public_market_data import PublicFinancialFact, PublicSourceDocument
from app.services.public_market_data import PublicMarketDataRepository


@pytest.fixture()
def engine():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Company(id=1, ticker='PUBLIC', name='Public issuer', exchange='NASDAQ', currency='USD', company_type='operating', valuation_model='standard_dcf'))
        db.commit()
    yield engine
    engine.dispose()


def seed_public(db, *, filed=date(2026, 1, 1), unit='USD', listing='US:PUBLIC'):
    source = PublicSourceDocument(company_id=1, listing_key=listing, provider='SEC',
        source_url='https://www.sec.gov/report', checksum='a' * 64,
        fetched_at=datetime(2026, 1, 2, tzinfo=UTC), official=True)
    db.add(source)
    db.flush()
    fact = PublicFinancialFact(source_document_id=source.id, metric='total_debt',
        value=Decimal('12'), unit=unit, period_end=date(2025, 12, 31),
        fiscal_quarter='FY', filed=filed, confidence=Decimal('1'), derived=False)
    db.add(fact)
    db.commit()
    return fact.id


def test_disabled_reader_does_not_even_query(monkeypatch):
    monkeypatch.setattr('app.services.public_market_data.get_settings',
                        lambda: SimpleNamespace(public_market_data_enabled=False))
    class NoSQL:
        def execute(self, *_):
            pytest.fail('flag off must not query any table')
    assert PublicMarketDataRepository().facts(NoSQL(), company_id=1,
        listing_key='US:PUBLIC', unit='USD', as_of=date(2026, 1, 2)) == []


def test_public_fact_same_for_two_tenants_private_fact_stays_private(engine, monkeypatch):
    monkeypatch.setattr('app.services.public_market_data.get_settings',
                        lambda: SimpleNamespace(public_market_data_enabled=True))
    with Session(engine) as db:
        public_id = seed_public(db)
        db.info['tenant_id'] = 2
        db.add(FinancialFact(company_id=1, metric='total_debt', value=Decimal('999'),
            unit='USD', period='2025-12-31:FY', source_type='manual'))
        db.commit()
    outputs = []
    for tenant in (2, 5):
        with Session(engine) as db:
            db.info['tenant_id'] = tenant
            facts = PublicMarketDataRepository().facts(db, company_id=1,
                listing_key='US:PUBLIC', unit='USD', as_of=date(2026, 1, 2))
            outputs.append(facts)
            assert [f.value for f in facts] == [Decimal('12')]
            assert facts[0].fact_ref == f'public:{public_id}'
            assert not any('tenant' in key or 'user' in key for key in vars(facts[0]))
            private = db.scalars(select(FinancialFact)).all()
            assert len(private) == (1 if tenant == 2 else 0)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize('filed,unit,listing', [
    (date(2027, 1, 1), 'USD', 'US:PUBLIC'),
    (None, 'USD', 'US:PUBLIC'),
    (date(2026, 1, 1), 'EUR', 'US:PUBLIC'),
    (date(2026, 1, 1), 'USD', 'BME:PUBLIC'),
])
def test_no_future_unknown_filing_currency_or_listing_mix(engine, monkeypatch, filed, unit, listing):
    monkeypatch.setattr('app.services.public_market_data.get_settings',
                        lambda: SimpleNamespace(public_market_data_enabled=True))
    with Session(engine) as db:
        seed_public(db, filed=filed, unit=unit, listing=listing)
        assert PublicMarketDataRepository().facts(db, company_id=1,
            listing_key='US:PUBLIC', unit='USD', as_of=date(2026, 1, 2)) == []


def test_only_new_public_tables_in_upgrade_and_default_off():
    from app.core.config import Settings
    assert Settings.model_fields['public_market_data_enabled'].default is False
    path = Path(__file__).parents[1] / 'alembic/versions/0128_public_market_data.py'
    spec = importlib.util.spec_from_file_location('public_migration', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []
    class Op:
        def get_bind(self):
            return create_engine('sqlite://').connect()
        def create_table(self, name, *args):
            calls.append(('table', name))
        def create_index(self, name, table, columns):
            calls.append(('index', table))
    mod.op = Op()
    mod.upgrade()
    assert {n for kind, n in calls if kind == 'table'} == {
        'public_source_documents', 'public_financial_facts',
        'public_financial_statements', 'public_analyst_targets'}
    assert all(n.startswith('public_') for _, n in calls)
    for name in ('public_source_documents', 'public_financial_facts', 'public_financial_statements', 'public_analyst_targets'):
        assert 'tenant_id' not in Base.metadata.tables[name].columns
