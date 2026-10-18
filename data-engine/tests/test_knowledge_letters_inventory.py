from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import KnowledgeDocument, Tenant
from app.services.knowledge_library_service import KnowledgeLibraryService


def test_letters_filter_is_before_limit_and_pages_have_stable_order():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id=1, external_id='letters-inventory'))
        db.flush()
        db.info['tenant_id'] = 1
        at = datetime(2026, 1, 1, tzinfo=UTC)
        db.add_all([
            KnowledgeDocument(id=i, title=f'Doc {i}', tenant_id=1,
                              document_type='fund_letter' if i <= 4 else 'book',
                              status='ready' if i != 4 else 'pending', created_at=at)
            for i in range(1, 510)
        ])
        db.flush()
        def page(offset):
            return KnowledgeLibraryService.list_documents(
                db, document_type='fund_letter', status='ready', limit=2, offset=offset)
        assert [row['id'] for row in page(0)] == [3, 2]
        assert [row['id'] for row in page(2)] == [1]
        assert page(4) == []
