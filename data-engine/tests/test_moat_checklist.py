from app.models import ClaimEvidence, Document, DocumentChunk
from app.services.moat_checklist import moat_checklist
from tests.test_moat_service import _claim, _company, db  # noqa: F401


def test_empty_is_sin_evidencia(db):
    rows = moat_checklist(db, _company(db))
    assert len(rows) == 5
    assert all(r['status'] == 'sin_evidencia' and not r['excerpts'] for r in rows)


def test_only_verbatim_company_chunk_with_document_url(db):
    company = _company(db)
    claim = _claim(db, company.id, 'LLM claims pricing power without support')
    doc = Document(company_id=company.id, title='Informe', source_type='sec_filing', source_url='https://example.com/report')
    db.add(doc); db.flush()
    quote = 'Our competitors introduced a substitute product and challenged our pricing power.'
    chunk = DocumentChunk(document_id=doc.id, chunk_index=0, text=quote)
    db.add(chunk); db.flush()
    ev = ClaimEvidence(claim_id=claim.id, document_id=doc.id, document_chunk_id=chunk.id, quote=quote, summary='unsupported summary', evidence_type='contradicts')
    db.add(ev); db.commit()
    rows = {r['id']: r for r in moat_checklist(db, company)}
    assert rows['competition']['excerpts'][0]['quote'] == quote
    assert rows['pricing']['excerpts'][0]['relation'] == 'contradicts'
    assert rows['ten_years']['status'] == 'sin_evidencia'
    ev.quote = 'Our pricing power is absolute and will last for ten years forever.'
    db.commit()
    assert all(not r['excerpts'] for r in moat_checklist(db, company))
    ev.quote = quote
    ev.source_url = 'https://example.com/unrelated'
    db.commit()
    assert all(not r['excerpts'] for r in moat_checklist(db, company))
