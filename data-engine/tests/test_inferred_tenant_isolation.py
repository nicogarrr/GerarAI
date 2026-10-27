"""Private inferred inputs never affect another tenant, including legacy NULL rows."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

from app.models import Company, InferredInput
from app.services.inferred_input_service import InferredInputService


@pytest.fixture()
def engine():
    from app.models.entities import Base
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Company(id=1, ticker='PRIVATE', name='Private', exchange='NASDAQ', company_type='growth', valuation_model='pre_revenue'))
        db.commit()
    yield engine
    engine.dispose()


def create(db, value='0.25'):
    return InferredInputService().create(
        db, db.get(Company, 1), input_key='fcf_margin', value=Decimal(value),
        base='Dado el margen publicado inferimos margen futuro.',
        source_urls=['https://example.com/report'],
    )


def test_other_tenant_cannot_read_or_change_owner_input(engine):
    with Session(engine) as owner:
        owner.info['tenant_id'] = 2
        row = create(owner)
        row_id = row.id
    with Session(engine) as other:
        other.info['tenant_id'] = 5
        assert InferredInputService().latest_valid(other, 1, 'fcf_margin') is None
        assert other.scalars(select(InferredInput)).all() == []
        assert other.get(InferredInput, row_id) is None
        other.execute(update(InferredInput).values(value=Decimal('0.4')))
        other.execute(delete(InferredInput))
        other.commit()
        create(other, '0.3')
    with Session(engine) as owner:
        owner.info['tenant_id'] = 2
        row = InferredInputService().latest_valid(owner, 1, 'fcf_margin')
        assert row.id == row_id and float(row.value) == 0.25


def test_unscoped_reads_fail_closed_and_writes_rejected(engine):
    with Session(engine) as owner:
        owner.info['tenant_id'] = 2
        create(owner)
    with Session(engine) as missing:
        assert missing.scalars(select(InferredInput)).all() == []
        assert InferredInputService().latest_valid(missing, 1, 'fcf_margin') is None
        with pytest.raises((RuntimeError, ValueError)):
            create(missing)


def test_legacy_null_owner_rows_preserved_but_not_shared(engine):
    # Raw connection simulates pre-fix data, never an application write.
    with engine.begin() as conn:
        conn.execute(InferredInput.__table__.insert().values(
            company_id=1, input_key='fcf_margin', value=Decimal('0.2'),
            base='Legacy documented inference with no known author',
            source_urls=['https://example.com/legacy'], origin='llm',
        ))
    for tenant in (2, 5, None):
        with Session(engine) as db:
            db.info['tenant_id'] = tenant
            assert InferredInputService().latest_valid(db, 1, 'fcf_margin') is None
    with Session(engine) as admin:
        rows = admin.scalars(select(InferredInput).execution_options(include_all_tenants=True)).all()
        assert len(rows) == 1 and rows[0].tenant_id is None


def test_cross_tenant_instance_write_and_explicit_owner_forgery_rejected(engine):
    with Session(engine) as owner:
        owner.info['tenant_id'] = 2
        row_id = create(owner).id
    with Session(engine) as other:
        other.info['tenant_id'] = 5
        row = other.scalar(select(InferredInput).execution_options(include_all_tenants=True))
        row.base = 'Attempted cross-tenant overwrite of original inference'
        with pytest.raises(RuntimeError):
            other.commit()
        other.rollback()
        other.add(InferredInput(id=row_id+1, tenant_id=2, company_id=1,
                                input_key='fcf_margin', value=Decimal('0.2'),
                                base='Forgery of another tenant input', source_urls=[]))
        with pytest.raises(RuntimeError):
            other.commit()
