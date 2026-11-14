"""El nombre de un 8-K puede llevar fecha del hecho, no de presentación.

Caso fuente SEC: 0000056978-26-000036.txt declara FILED AS OF DATE
20261014 y su documento klic-20261013.htm lleva la fecha del hecho.
https://www.sec.gov/Archives/edgar/data/56978/0000056978-26-000036.txt
"""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.eight_k_digest import _filed_at, eight_k_digest
from tests.test_eight_k_digest import _db, _document


@pytest.mark.parametrize('url,title', [
    ('https://www.sec.gov/Archives/edgar/data/56978/000005697826000036/klic-20261013.htm', '8-K'),
    ('https://www.sec.gov/Archives/edgar/data/1/2/report.htm', 'Evento 20261013'),
    ('https://www.sec.gov/Archives/edgar/data/1/2/report.htm?date=20261013', '8-K'),
])
def test_missing_filing_date_is_not_reconstructed_from_arbitrary_text(url, title):
    document = SimpleNamespace(published_at=None, source_url=url, title=title)
    assert _filed_at(document) is None


def test_verified_publication_date_takes_precedence_over_name():
    document = SimpleNamespace(published_at=datetime(2026, 10, 14, tzinfo=UTC),
                               source_url='klic-20261013.htm', title='Evento 20261013')
    assert _filed_at(document) == '2026-10-14'


def test_digest_retains_undated_document_without_inventing_filed_at():
    db = _db()
    try:
        doc = _document({'form': '8-K', 'items': '5.02'})
        doc.published_at = None
        db.add(doc)
        db.commit()
        entry = eight_k_digest(db)['items'][0]
        assert entry['filed_at'] is None
        assert entry['source_url'] == doc.source_url
        assert entry['items'][0]['code'] == '5.02'
    finally:
        db.close()
