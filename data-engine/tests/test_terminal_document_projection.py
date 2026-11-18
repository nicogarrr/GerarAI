"""La terminal solo necesita identidad, enlace y segmento del documento."""
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models import Document, FinancialFact
from app.services.financial_terminal_service import FinancialTerminalService
from tests.test_financial_terminal_service import _company, db  # noqa: F401


@pytest.mark.parametrize('segment', [None, '', 'Europe', 0, 12, ['uno'], {'region': 'sur'}])
def test_document_projection_preserves_segment_and_source(db, segment):
    company = _company(db)
    doc = Document(company_id=company.id, title='Informe anual', source_type='SEC',
                   source_url='https://example.org/report',
                   metadata_={'segment': segment, 'irrelevant': 'x' * 100_000})
    db.add(doc)
    db.flush()
    fact = FinancialFact(company_id=company.id, metric='revenue', value=Decimal('123'),
                         period='FY2025', fiscal_year=2025, source_type='SEC', source_id=doc.id)
    db.add(fact)
    db.commit()
    company_id = company.id
    db.expunge(doc)
    hydrated = []
    def record(session, obj):
        if isinstance(obj, Document):
            hydrated.append(obj)
    event.listen(db, 'loaded_as_persistent', record)
    try:
        out = FinancialTerminalService().build(db, db.get(type(company), company_id), metrics=['revenue'])
    finally:
        event.remove(db, 'loaded_as_persistent', record)
    row = out['metrics'][0]['series'][0]
    assert row['segment'] == str(segment or 'consolidated')
    assert row['source']['title'] == 'Informe anual'
    assert row['source']['url'] == 'https://example.org/report'
    assert hydrated == []


def test_foreign_tenant_source_is_not_disclosed(db):
    from sqlalchemy.orm import Session

    company = _company(db)
    with Session(db.get_bind()) as other:
        other.info['tenant_id'] = 'other-tenant'
        doc = Document(company_id=company.id, title='Privado', source_type='SEC',
                       source_url='https://example.org/private', metadata_={'segment': 'secreto'})
        other.add(doc)
        other.commit()
        doc_id = doc.id
    db.add(FinancialFact(company_id=company.id, metric='revenue', value=Decimal('12'),
                        period='FY2025', fiscal_year=2025, source_type='SEC', source_id=doc_id))
    db.commit()
    out = FinancialTerminalService().build(db, company, metrics=['revenue'])
    row = out['metrics'][0]['series'][0]
    assert row['source']['title'] is None
    assert row['source']['url'] is None
    assert row['segment'] == 'consolidated'

