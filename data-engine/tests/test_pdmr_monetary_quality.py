"""Five actual provider errors retain evidence without publishing bad money."""
import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.entities import Company, InsiderTransaction
from app.services.connectors.uk_pdmr_tracefour import map_entry
from app.services.pdmr_monetary_quality import monetary_fields, pdmr_monetary_quality
from app.services.uk_pdmr_ingestion import ingest_uk_pdmr
from tests.test_uk_pdmr_ingestion import _client_with, db  # noqa: F401 - fixture

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'pdmr_monetary_inconsistent.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['provider_row']['filingId'])
def test_real_errors_keep_raw_evidence_but_not_operational_money(case):
    row = case['provider_row']
    result = map_entry(row)
    assert result['price'] is None and result['value'] is None
    assert result['shares'] == row['volume']
    assert result['source_url'] == case['fca_url']
    quality = result['monetary_quality']
    assert quality['provider_monetary_inconsistent'] is True
    assert quality['monetary_verification'] == 'inconsistent'
    assert quality['provider_reported_price'] == row['pricePerShare']
    assert quality['provider_reported_value'] == row['totalValue']
    assert quality['monetary_source_url'] == case['fca_url']
    assert case['fca_excerpt']


def test_unreviewed_does_not_claim_confirmed_error():
    assert pdmr_monetary_quality('unreviewed') == {'monetary_verification': 'unverified', 'provider_monetary_inconsistent': False}
    assert monetary_fields('PDMR', 'unreviewed', 2, 200)['value'] is None


@pytest.mark.parametrize('form', ['4', '4/A', '5', '5/A', 'CA-INSIDER', None])
def test_other_forms_are_not_changed(form):
    assert monetary_fields(form, CASES[0]['provider_row']['filingId'], 2, 200) == {'price': 2, 'value': 200}


def test_ingestion_preserves_all_five_rows_and_their_evidence(db):
    rows = [c['provider_row'] for c in CASES]
    for index, isin in enumerate(sorted({r['isin'] for r in rows})):
        db.add(Company(ticker=f'PDMR{index}', name='PDMR test', isin=isin, exchange='LSE', currency='USD', company_type='research_candidate', valuation_model='unassigned'))
    db.commit()

    async def run():
        return await ingest_uk_pdmr(db, 1, client=_client_with(rows))

    result = asyncio.run(run())
    assert result['saved'] == 5
    stored = db.scalars(select(InsiderTransaction).where(InsiderTransaction.form == 'PDMR')).all()
    assert len(stored) == 5
    for tx in stored:
        assert tx.price is None and tx.value is None
        assert tx.shares > 0
        assert tx.data_quality['provider_monetary_inconsistent'] is True
        assert tx.data_quality['provider_reported_value'] > 0
        assert tx.source_url == tx.data_quality['monetary_source_url']


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['provider_row']['filingId'])
def test_legacy_rows_are_guarded_at_every_public_money_reader(db, case):
    """No reingestion needed: old raw money stays stored but cannot leak out."""
    from datetime import date

    from app.api.routes.insider import insider_filings
    from app.models.entities import InsiderFiling
    from app.services.company_events_service import stored_timeline_events
    from app.services.insider_alerts import _candidate_purchases
    from app.services.insider_feed import _tx_dict, build_feed
    from app.services.insider_service import _persisted_filing_transactions
    from app.services.insider_summary import insider_summary
    from app.services.management_alignment import insider_windows
    from app.services.ticker_ownership_signals import insider_signal

    raw = case['provider_row']
    filing = InsiderFiling(tenant_id=1, accession_number=raw['filingId'], form='PDMR',
                          issuer_ticker='CGEO.L', issuer_cik='UK', parser_version='1', filing_date='2026-11-13', source_url=case['fca_url'])
    db.add(filing)
    db.flush()
    tx = InsiderTransaction(tenant_id=1, filing_id=filing.id, fingerprint=raw['filingId'],
                            accession_number=raw['filingId'], form='PDMR', issuer_ticker='CGEO.L',
                            insider=raw['pdmrName'], code='P', acquired_disposed='A', is_derivative=False,
                            shares=raw['volume'], price=raw['pricePerShare'], value=raw['totalValue'],
                            tx_date='2026-11-13', source_url=case['fca_url'], data_quality={'currency':'USD'})
    db.add(tx)
    db.commit()
    public = [_tx_dict(tx, filing, 0),
              build_feed(db, today=date(2026,11,14))['transactions'][0],
              insider_filings(ticker='CGEO.L', limit=20, offset=0, db=db)['filings'][0]['transactions'][0]]
    persisted = _persisted_filing_transactions(db, raw['filingId'], 1, 'CGEO.L', {})
    public.append(persisted[0][0])
    summary = insider_summary(db, 'CGEO.L', as_of=date(2026,11,14))
    public.append(summary['transactions'][0])
    for row in public:
        assert row['price'] is None and row['value'] is None
        assert row['monetary_verification'] == 'inconsistent'
    assert all(w['net_value'] is None and w['buys']['value'] is None for w in summary['windows'])
    assert summary['by_nature']['compra_mercado']['value'] is None
    assert summary['transactions_total'] == 1
    company = db.get(Company, 1)
    timeline = stored_timeline_events(db, company, date(2026,11,1), date(2026,11,30))
    assert 'sin verificar' in timeline[0]['detail']
    assert insider_signal(db, 'CGEO.L', as_of=date(2026,11,14))['status'] == 'sin_datos'
    assert _candidate_purchases(db, 1, today=date(2026,11,14)) == []
    from app.services.brain_data_tools import _recent_insider_txs
    assert _recent_insider_txs(db, 1, 'CGEO.L', 20) == []
    alignment = insider_windows([(tx, filing.filing_date)], date(2026,11,14))
    assert alignment
    assert all(w['net_value'] is None for w in alignment)
    # Reads do not rewrite or delete source evidence.
    db.refresh(tx)
    assert tx.price == raw['pricePerShare'] and tx.value == raw['totalValue']
