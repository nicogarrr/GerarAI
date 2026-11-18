"""Review gates for the document-only terminal projection."""
import inspect
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.core.database as coredb
import app.core.tenancy as tenancy
from app.models import CalculatedMetric, Company, Document, FinancialFact, Tenant
from app.models.entities import Base
from app.services.financial_terminal_service import FinancialTerminalService
from tests.test_financial_terminal_service import _company, db  # noqa: F401

METADATA_CASES = [
    {'segment': value} for value in
    [None, '', 'Europe', 0, 12, 1.5, ['uno'], {'region': 'sur'}, False, '0', [], {}, True]
] + [{}, None]


def add_source(db, company, metadata):
    doc = Document(company_id=company.id, title='Informe', source_type='SEC', metadata_=metadata)
    db.add(doc)
    db.flush()
    db.add(FinancialFact(company_id=company.id, metric='revenue', value=12,
                         period='FY2025', fiscal_year=2025, source_type='SEC', source_id=doc.id))
    db.commit()
    return doc.id


def test_production_dependency_supplies_tenant_to_real_route(db, monkeypatch):
    from app.api.routes.companies import financial_terminal

    config = SimpleNamespace(is_production=True, research_auth_required=True)
    monkeypatch.setattr(coredb, 'settings', config)
    monkeypatch.setattr(tenancy, 'get_settings', lambda: config)
    monkeypatch.setattr(coredb, 'SessionLocal', sessionmaker(db.get_bind(), expire_on_commit=False))
    # Lock the actual route wiring as well as executing get_db and the real service.
    assert inspect.signature(financial_terminal).parameters['db'].default.dependency is coredb.get_db
    generator = coredb.get_db(principal=SimpleNamespace(
        tenant_external_id='route-review', user_id='reviewer', email=None), request=None)
    scoped = next(generator)
    try:
        assert scoped.info['tenant_id'] > 0
        company = _company(scoped)
        add_source(scoped, company, {'segment': 'Europe'})
        result = financial_terminal('AAA', metrics='revenue', years=10, periodicity='all', db=scoped)
        assert result['metrics'][0]['series'][0]['segment'] == 'Europe'
    finally:
        generator.close()


def test_missing_production_tenant_is_explicitly_fail_closed(db, monkeypatch):
    company = _company(db)
    add_source(db, company, {'segment': 'Europe'})
    db.info.pop('tenant_id')
    monkeypatch.setattr(tenancy, 'get_settings', lambda: SimpleNamespace(
        is_production=True, research_auth_required=False))
    with pytest.raises(RuntimeError, match='Tenant context is required'):
        FinancialTerminalService().build(db, company, metrics=['revenue'])


def test_explicit_document_filter_survives_disabled_loader_criteria(db):
    company = _company(db)
    with Session(db.get_bind()) as other:
        other.info['tenant_id'] = 'foreign'
        doc_id = add_source(other, company, {'segment': 'Privado'})
    # The foreign fact is scoped out. The active tenant references its document.
    db.add(FinancialFact(company_id=company.id, metric='revenue', value=12,
                         period='FY2025', fiscal_year=2025, source_type='SEC', source_id=doc_id))
    db.commit()
    # Exercise the explicit predicate independently of the global ORM guard.
    # Restore the listener even on assertion/query failure. This test is isolated
    # within its pytest process and never touches production configuration.
    event.remove(Session, 'do_orm_execute', coredb._scope_tenant_queries)
    try:
        result = FinancialTerminalService().build(db, company, metrics=['revenue'])
    finally:
        event.listen(Session, 'do_orm_execute', coredb._scope_tenant_queries)
    row = result['metrics'][0]['series'][0]
    assert row['source']['title'] is None
    assert row['source']['url'] is None
    assert row['segment'] == 'consolidated'


@pytest.fixture
def postgres_db():
    url = os.environ.get('TERMINAL_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Set TERMINAL_TEST_POSTGRES_URL for a disposable PostgreSQL database')
    engine = create_engine(url)
    schema = 'terminal_review_' + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped_engine, tables=[Tenant.__table__, Company.__table__,
            Document.__table__, FinancialFact.__table__, CalculatedMetric.__table__])
        with Session(scoped_engine, expire_on_commit=False) as session:
            session.add(Tenant(id=1, external_id='review'))
            session.commit()
            session.info['tenant_id'] = 1
            yield session
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()


@pytest.mark.services
@pytest.mark.parametrize('metadata', METADATA_CASES)
def test_postgres_segment_projection_equals_old_conversion(postgres_db, metadata):
    db = postgres_db
    company = _company(db)
    doc_id = add_source(db, company, metadata)
    hydrated = db.scalar(select(Document).where(Document.id == doc_id))
    old = str((hydrated.metadata_ or {}).get('segment') or 'consolidated')
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = FinancialTerminalService().build(db, company, metrics=['revenue'])
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert result['metrics'][0]['series'][0]['segment'] == old
    assert any(' -> ' in sql and ' ->> ' not in sql for sql in statements)
