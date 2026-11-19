"""No latest thesis means no generation imports, with unchanged gap semantics."""
import builtins

import pytest
from sqlalchemy import event

from app.models import ThesisVersion
from app.services import fair_value_service as fvs
from tests.test_fair_value_service import _company, db  # noqa: F401


@pytest.mark.parametrize(('status', 'value', 'tenant'), [
    (None, None, 2), ('draft', 150, 2), ('published', None, 2),
    ('published', 150, 5),
])
def test_no_visible_thesis_skips_generation_imports(db, monkeypatch, status, value, tenant):
    company = _company(db, 'COLD')
    if status is not None:
        db.add(ThesisVersion(company_id=company.id, tenant_id=tenant, version=1,
                             status=status, expected_value=value, thesis_markdown='Synthetic',
                             executive_summary='Synthetic'))
    db.commit()
    company_id = company.id
    db.info['tenant_id'] = 2
    attempted, statements = [], []
    original = builtins.__import__

    def record_import(name, *args, **kwargs):
        attempted.append(name)
        return original(name, *args, **kwargs)

    def record_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith('SELECT'):
            statements.append(statement)

    monkeypatch.setattr(builtins, '__import__', record_import)
    bind = db.get_bind()
    event.listen(bind, 'before_cursor_execute', record_sql)
    gaps = {-1: 'existing gap'}
    try:
        assert fvs.thesis_candidates(db, [company_id], gaps=gaps) == {}
    finally:
        event.remove(bind, 'before_cursor_execute', record_sql)
    assert gaps == {-1: 'existing gap'}
    assert len(statements) == 1
    assert not any(name.startswith(('app.services.thesis_service', 'qdrant_client', 'llama_index'))
                   for name in attempted)


def test_no_thesis_ids_needs_no_database_or_imports():
    assert fvs.thesis_candidates(None, []) == {}
