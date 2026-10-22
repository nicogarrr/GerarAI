"""Read-only SQLite adapter tests; no conftest, source fetch or live account."""
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, DocumentChunk, FinancialFact
from app.services.commitment_followup_service import evaluate_followup, load_reported_evidence
from tests.test_commitment_followup_service import CRITERION, TODAY

URL = 'https://issuer.invalid/filing/2031'


class AdapterTests(unittest.TestCase):
    def test_collection_preserves_database_url_and_cross_thread_schema(self):
        # Regression: module-level DATABASE_URL='sqlite://' replaced the
        # conftest file DB during collection; HTTP's other thread saw no tables.
        import os
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            database_url = 'sqlite:///' + (Path(directory) / 'collection.db').as_posix()
            environment = {**os.environ, 'APP_ENV': 'test', 'DATABASE_URL': database_url}
            script = """
import os
from concurrent.futures import ThreadPoolExecutor
expected = os.environ['DATABASE_URL']
import tests.test_commitment_followup_adapter
assert os.environ['DATABASE_URL'] == expected
from app.core.database import engine
from sqlalchemy import text
assert str(engine.url) == expected
with engine.begin() as connection:
    connection.execute(text('create table collection_probe (id integer)'))
def read_from_http_thread():
    with engine.connect() as connection:
        connection.execute(text('select * from collection_probe'))
with ThreadPoolExecutor(max_workers=1) as pool:
    pool.submit(read_from_http_thread).result()
"""
            probe = subprocess.run([sys.executable, '-c', script], env=environment,
                                   capture_output=True, text=True, timeout=20,
                                   cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(probe.returncode, 0, probe.stderr)

    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.info['tenant_id'] = 1
        company = Company(id=8, ticker='FIXT', name='Fixture', exchange='NYSE', currency='USD',
                          sector='test', industry='test', company_type='holding',
                          valuation_model='unassigned', special_sources=[], special_risks=[], factor_tags=[])
        self.db.add(company)
        self.db.commit()
        self.document = Document(company_id=8, title='Annual filing', source_type='SEC', source_url=URL,
                                 published_at=datetime(2032, 1, 20, tzinfo=UTC))
        self.db.add(self.document)
        self.db.flush()
        self.chunk = DocumentChunk(document_id=self.document.id, chunk_index=0,
                                   text='revenue | 120 | USD | 2031-12-31:FY')
        self.fact = FinancialFact(company_id=8, source_id=self.document.id, metric='revenue',
                                  value=Decimal('120'), unit='USD', period='2031-12-31:FY',
                                  fiscal_year=2031, fiscal_quarter='FY', source_type='SEC',
                                  is_reported=True, is_adjusted=False)
        self.db.add_all([self.chunk, self.fact])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def load(self, **kwargs):
        return load_reported_evidence(self.db, CRITERION, official_urls=frozenset({URL}), today=TODAY, **kwargs)

    def test_reads_literal_dated_evidence_and_does_not_write(self):
        statements = []
        from sqlalchemy import event
        event.listen(self.engine, 'before_cursor_execute', lambda c, cur, stmt, p, ctx, many: statements.append(stmt))
        items = self.load()
        self.assertEqual(len(items), 1)
        self.assertEqual(evaluate_followup(CRITERION, items, today=TODAY).status, 'fulfilled')
        self.assertTrue(all(stmt.lstrip().upper().startswith('SELECT') for stmt in statements))
        self.assertFalse(self.db.dirty)
        self.assertFalse(self.db.new)

    def test_unregistered_url_generic_provider_and_unquoted_fact_are_rejected(self):
        self.assertEqual(load_reported_evidence(self.db, CRITERION, official_urls=frozenset(), today=TODAY), ())
        self.document.source_type = 'FMP'
        self.db.commit()
        self.assertEqual(self.load(), ())
        self.document.source_type = 'SEC'
        self.chunk.text = 'We expect revenue of 120 USD for next year.'
        self.db.commit()
        self.assertEqual(self.load(), ())

    def test_other_tenant_session_refused_and_foreign_source_join_excluded(self):
        self.db.info['tenant_id'] = 2
        with self.assertRaises(ValueError):
            self.load()
        self.db.info['tenant_id'] = 1
        # Deliberately corrupt synthetic DB below ORM safeguards to prove
        # the read adapter also excludes a mismatched foreign source.
        with self.engine.begin() as conn:
            conn.execute(Document.__table__.update().where(Document.id == self.document.id).values(tenant_id=2))
        self.db.expire_all()
        self.assertEqual(self.load(), ())

    def test_cross_company_source_and_foreign_chunk_are_not_evidence(self):
        self.document.company_id = None
        self.db.commit()
        self.assertEqual(self.load(), ())
        self.document.company_id = 8
        self.db.commit()
        with self.engine.begin() as conn:
            conn.execute(DocumentChunk.__table__.update().where(DocumentChunk.id == self.chunk.id).values(tenant_id=2))
        self.db.expire_all()
        self.assertEqual(self.load(), ())

    def test_missing_date_period_mismatch_and_nonreported_data_are_not_evidence(self):
        for field, value in [('published_at', None), ('source_url', 'https://other.invalid/file')]:
            original = getattr(self.document, field)
            setattr(self.document, field, value)
            self.db.commit()
            self.assertEqual(self.load(), ())
            setattr(self.document, field, original)
            self.db.commit()
        for field, value in [('period', 'FY2031'), ('period', '2031-09-30:Q3'),
                             ('is_reported', False), ('is_adjusted', True), ('source_type', 'FMP')]:
            original = getattr(self.fact, field)
            setattr(self.fact, field, value)
            self.db.commit()
            self.assertEqual(self.load(), ())
            setattr(self.fact, field, original)
            self.db.commit()

    def test_bounded_reads_raise_instead_of_silently_picking_fact_or_chunk(self):
        extra = FinancialFact(company_id=8, source_id=self.document.id, metric='revenue',
                              value=Decimal('90'), unit='USD', period='2031-12-31:FY',
                              source_type='SEC', is_reported=True, is_adjusted=False)
        self.db.add(extra)
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Demasiados hechos'):
            self.load(max_facts=1)
        self.db.delete(extra)
        self.db.add(DocumentChunk(document_id=self.document.id, chunk_index=1, text='other'))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Documento demasiado grande'):
            self.load(max_chunks_per_document=1)

    def test_pending_session_changes_are_not_flushed(self):
        self.fact.value = Decimal('999')
        with self.assertRaisesRegex(ValueError, 'cambios pendientes'):
            self.load()
        # Identity map may contain pending edits; adapter must not return those
        # edits as a verified persisted fact. Explicit dirty guard is required.
        with self.assertRaises(ValueError):
            load_reported_evidence(self.db, replace(CRITERION, tenant_id=2),
                                   official_urls=frozenset({URL}), today=TODAY)
        self.db.rollback()
        self.assertEqual(self.db.scalar(select(FinancialFact.value)), Decimal('120'))


if __name__ == '__main__':
    unittest.main()
