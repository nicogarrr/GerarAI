"""Offline recorded filings, plus explicitly labelled controlled interventions.

No generated value is claimed to be a real corporate action or filing.
"""
from __future__ import annotations

import asyncio
import copy
import gzip
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, CorporateAction, InsiderTransaction
from app.services import financial_ingestion_service as ingestion
from app.services import management_alignment as m
from app.services.connectors.form4 import parse_form4_xml

ROOT = Path(__file__).parent / 'fixtures'
META = ROOT / 'form4/meta_0000950103-26-016314.xml'
META_BASE_SHA256 = '8b64b5f299d01ca9583247075096a4486ff4b6e54a1457aef749fb0f7b52ef79'


def meta_bytes():
    # Integrity pin against the existing repository base, NOT independent retrieval provenance.
    raw = META.read_bytes()
    assert len(raw) == 3835 and hashlib.sha256(raw).hexdigest() == META_BASE_SHA256
    return raw

AS_OF = date(2026, 11, 11)


def test_recorded_meta_plan_is_attributed_by_unique_transaction_note_not_root_alone():
    parsed = parse_form4_xml(meta_bytes())
    assert parsed['ticker'] == 'META' and len(parsed['transactions']) == 1
    tx = parsed['transactions'][0]
    assert tx['type'] == 'S' and tx['shares'] == 390 and tx['price'] == 640
    assert tx['rule_10b5_1'] is True  # legacy is unchanged
    assert tx['alignment_10b5_1'] is True  # F1 affirms THIS sale, unique coding reference


@pytest.mark.parametrize('intervention', [
    'remove-note', 'remove-reference', 'root-false', 'root-absent', 'ambiguous-language',
    'negated-language', 'note-on-holdings-only', 'shared-note', 'purchase-not-sale', 'duplicate-declaration',
])
def test_controlled_meta_variants_do_not_copy_root_mark_to_transactions(intervention):
    root = ET.fromstring(meta_bytes())
    tx = root.find('nonDerivativeTable/nonDerivativeTransaction')
    coding = tx.find('transactionCoding')
    note = root.find("footnotes/footnote[@id='F1']")
    if intervention == 'remove-note':
        root.find('footnotes').remove(note)
    elif intervention == 'remove-reference':
        coding.remove(coding.find('footnoteId'))
    elif intervention == 'root-false':
        root.find('aff10b5One').text = '0'
    elif intervention == 'root-absent':
        root.remove(root.find('aff10b5One'))
    elif intervention == 'ambiguous-language':
        note.text = 'The reporting person may sell under a Rule 10b5-1 plan.'
    elif intervention == 'negated-language':
        note.text = 'The sale reported was not effected pursuant to a Rule 10b5-1 trading plan.'
    elif intervention == 'note-on-holdings-only':
        coding.remove(coding.find('footnoteId'))
        ET.SubElement(tx.find('postTransactionAmounts'), 'footnoteId', {'id': 'F1'})
    elif intervention == 'shared-note':
        root.find('nonDerivativeTable').append(copy.deepcopy(tx))
    elif intervention == 'duplicate-declaration':
        root.find('footnotes').append(copy.deepcopy(note))
    elif intervention == 'purchase-not-sale':
        coding.find('transactionCode').text = 'P'
    parsed = parse_form4_xml(ET.tostring(root))
    assert all(t['alignment_10b5_1'] is None for t in parsed['transactions'])


def test_mixed_transactions_only_the_uniquely_referenced_sale_is_classified():
    root = ET.fromstring(meta_bytes())
    table = root.find('nonDerivativeTable')
    other = copy.deepcopy(table[0])
    other.find('transactionCoding').remove(other.find('transactionCoding/footnoteId'))
    table.append(other)
    rows = parse_form4_xml(ET.tostring(root))['transactions']
    assert [r['alignment_10b5_1'] for r in rows] == [True, None]
    # An explicit transaction Boolean remains authoritative for that row only.
    ET.SubElement(other.find('transactionCoding'), 'aff10b5One').text = 'false'
    assert [r['alignment_10b5_1'] for r in parse_form4_xml(ET.tostring(root))['transactions']] == [True, False]


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.mark.parametrize('ticker,sbc,repurchases,shares,basis,revenue', [
    ('UNH', 971000000, 5545000000, 906000000, 'shares_outstanding', 447567000000),
    ('PLTR', 684033000, 74985000, 2391192000, 'shares_outstanding', 4475446000),
    ('CHTR', 673000000, 5132000000, 137743676, 'shares_diluted', 54774000000),
])
def test_original_companyfacts_through_ingestion_and_snapshot(db, monkeypatch, ticker, sbc, repurchases, shares, basis, revenue):
    raw = gzip.decompress((ROOT / f'sec_debt/{ticker.lower()}.json.gz').read_bytes())
    manifest = json.loads((ROOT / f'sec_debt/{ticker.lower()}.source.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == manifest['sha256'] and len(raw) == manifest['bytes']
    payload = json.loads(raw)
    # Build an offline submissions contract from the recorded annual facts.
    # This is NOT an independently verified submissions fixture or a network ingestion test.
    ends = {}
    for namespace in payload['facts'].values():
        for concept in namespace.values():
            for entries in concept.get('units', {}).values():
                for entry in entries:
                    if entry.get('form') in {'10-K', '10-K/A'} and entry.get('accn') and entry.get('end') and entry.get('start') and 300 <= (date.fromisoformat(entry['end']) - date.fromisoformat(entry['start'])).days <= 380:
                        ends[entry['accn']] = max(ends.get(entry['accn'], ''), entry['end'])
    class RecordedSEC:
        async def cik_for_ticker(self, *args, **kwargs):
            return str(payload['cik']).zfill(10)
        async def company_facts(self, cik):
            return payload
        async def annual_report_anchors(self, cik):
            return ends
        async def index_accessions(self, cik):
            return set(ends)
    async def no_extra_network(*args, **kwargs):
        return {'status': 'unavailable', 'recent_filings': [], 'macro': None}
    monkeypatch.setattr(ingestion, 'SECClient', RecordedSEC)
    monkeypatch.setattr(ingestion, '_free_data_snapshot', no_extra_network)
    # Disable extension/instance fallback: only these recorded bytes are evidence.
    async def no_instance(*args, **kwargs):
        return None
    monkeypatch.setattr(ingestion, '_merge_latest_filing_instance', no_instance)
    from app.services import sec_extension_facts
    monkeypatch.setattr(sec_extension_facts, 'resolve_latest_filing', no_instance)
    company = Company(ticker=ticker, name=payload['entityName'], cik=str(payload['cik']).zfill(10), currency='USD', exchange='NYSE', company_type='holding', valuation_model='unassigned')
    db.add(company); db.commit()
    asyncio.run(ingestion.FinancialIngestionService().refresh_from_sec(db=db, company=company))
    row = next(y for y in m.recompute_alignment(db, company, today=AS_OF).payload['years'] if y['year'] == 2025)
    assert row['sbc']['value'] == sbc and row['repurchases']['value'] == repurchases
    assert row['shares']['value'] == shares and row['share_basis'] == basis
    prior_expected = {'UNH': 915000000, 'PLTR': 2338795000, 'CHTR': 145363771}[ticker]
    previous = next(y for y in m.recompute_alignment(db, company, today=AS_OF).payload['years'] if y['year'] == 2024)
    assert previous['shares']['value'] == prior_expected
    # 2024 comparatives repeated in the 2025 accession stay 2024, not filing-fy 2025.
    assert previous['shares']['date'] == '2024-12-31' and row['shares']['date'] == '2025-12-31'
    assert previous['shares']['url'] == row['shares']['url']
    expected_change = float(((Decimal(shares) / Decimal(prior_expected) - 1) * 100).quantize(Decimal('.1'), rounding='ROUND_HALF_UP'))
    assert row['shares_change_pct']['value'] == expected_change
    expected = float((Decimal(sbc) / Decimal(revenue) * 100).quantize(Decimal('.1'), rounding='ROUND_HALF_UP'))
    assert row['sbc_revenue_pct']['value'] == expected
    assert all(s['url'] and s['filed'] for s in row['sbc_revenue_pct']['sources'])
    # Controlled corporate-action interventions on REAL balances, not claimed real events.
    baseline = row['shares_change_pct']['value']
    assert baseline is not None
    event = CorporateAction(company_id=company.id, action_type='ticker_change', effective_date=date(2025, 5, 1))
    db.add(event); db.flush()
    after_rename = next(y for y in m.recompute_alignment(db, company, today=AS_OF).payload['years'] if y['year'] == 2025)
    assert after_rename['shares_change_pct']['value'] == baseline
    for action_type in ['split', 'reverse_split']:
        event.action_type = action_type
        db.flush()
        after_split = next(y for y in m.recompute_alignment(db, company, today=AS_OF).payload['years'] if y['year'] == 2025)
        assert after_split['shares_change_pct']['value'] is None
        assert 'split' in after_split['shares_change_pct']['reason']



def test_recorded_meta_persistence_enriches_unknown_then_excludes_planned_sale(db):
    from app.services.insider_persistence import persist_filing
    filing = {'accession_number': '0000950103-26-016314', 'form': '4', 'filing_date': '2026-10-28',
              'document_url': 'https://example.com/recorded-meta-fixture.xml'}
    # Controlled removal of attribution first. The original recorded bytes come second.
    root = ET.fromstring(meta_bytes())
    root.find('nonDerivativeTable/nonDerivativeTransaction/transactionCoding').remove(root.find('nonDerivativeTable/nonDerivativeTransaction/transactionCoding/footnoteId'))
    persist_filing(db, filing, parse_form4_xml(ET.tostring(root)))
    tx = db.scalar(select(InsiderTransaction))
    assert tx.data_quality['alignment_10b5_1'] is None
    legacy = tx.rule_10b5_1
    persist_filing(db, filing, parse_form4_xml(meta_bytes()))
    assert tx.data_quality['alignment_10b5_1'] is True and tx.rule_10b5_1 == legacy
    w = m.insider_windows([(tx, '2026-10-28')], AS_OF)[1]
    assert w['net_value'] == -249600 and w['discretionary_net_value'] == 0
    assert len(w['groups']['planned_sales']) == 1 and not w['groups']['unknown_sales']



@pytest.mark.parametrize('table_tag,holding_tag', [
    ('nonDerivativeTable', 'nonDerivativeHolding'), ('derivativeTable', 'derivativeHolding'),
])
def test_shared_note_between_sale_and_holding_is_unknown(table_tag, holding_tag):
    root = ET.fromstring(meta_bytes())
    table = root.find(table_tag)
    if table is None:
        table = ET.SubElement(root, table_tag)
    holding = ET.SubElement(table, holding_tag)
    security = ET.SubElement(holding, 'securityTitle')
    ET.SubElement(security, 'value').text = 'Class A Common Stock'
    ET.SubElement(security, 'footnoteId', {'id': 'F1'})
    rows = parse_form4_xml(ET.tostring(root))['transactions']
    assert len(rows) == 1
    assert rows[0]['alignment_10b5_1'] is None
    # Remove only the second reference: unique sale attribution is restored.
    table.remove(holding)
    assert parse_form4_xml(ET.tostring(root))['transactions'][0]['alignment_10b5_1'] is True
