"""Original quote roundtrip, including a short excerpt from official UBER PDF.

Source read 2026-10-22:
https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/Uber-Q2-26-Earnings-Call-Transcript.pdf
PDF p3. This fixture is a small original excerpt, not live holdings evidence.
"""
import hashlib
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.services.followup_primary_evidence_adapter import (
    PrimaryAsset,
    ReportedObservation,
    asset_from_registry,
    extract_primary_evidence,
)

URL = 'https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/Uber-Q2-26-Earnings-Call-Transcript.pdf'
ASSET = PrimaryAsset('UBER', URL, 'Q2 2026', date(2026, 8, 5), 'transcript')
FACT = ReportedObservation(1, 8, 42, 'gross_bookings_growth_yoy', Decimal('22'), '%', URL, 'Q2 2026', True, False)
HEADER = 'Uber Technologies, Inc. (UBER)\nQ2 2026 Earnings Call\n05-Aug-2026\n\n'
QUOTE = ('Gross bookings grew 22% year-on-year to more than\n'
         '$58 billion, above the high end of our guidance and marking our fourth consecutive quarter above 20% growth.')
PREAMBLE = 'So, Q2 was another outstanding quarter for Uber with record cash generation. '
TEXT = HEADER + '\f' + HEADER + '\f' + HEADER + PREAMBLE + QUOTE
TODAY = date(2026, 10, 22)


class PrimaryEvidenceTests(unittest.TestCase):
    def extract(self, text=TEXT, fact=FACT, asset=ASSET, **kwargs):
        return extract_primary_evidence(tenant_id=1, company_id=8, asset=asset,
                                        source_url=URL, original_text=text, fact=fact,
                                        today=TODAY, **kwargs)

    def test_real_official_excerpt_roundtrips_original_span_page_hash(self):
        result = self.extract()
        self.assertEqual(result.reason_code, 'literal_reported_result')
        evidence = result.evidence
        self.assertEqual(evidence.quote, QUOTE)
        self.assertEqual(TEXT[evidence.char_start:evidence.char_end], evidence.quote)
        self.assertEqual(evidence.page, 3)
        self.assertEqual(evidence.text_sha256, hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertLessEqual(len(evidence.quote), 300)
        self.assertEqual(evidence.value, Decimal('22'))
        self.assertEqual(evidence.kind, 'document_quote')
        self.assertNotIn('|', evidence.quote)  # no synthetic normalized row

    def test_guidance_not_actual_even_when_target_number_matches(self):
        for phrase in ['We expect Gross bookings grew 22% year-on-year.',
                       'Our forecast: Gross bookings grew 22% year-on-year.',
                       'We aim for Gross bookings grew 22% year-on-year.']:
            self.assertIsNone(self.extract(text=HEADER + PREAMBLE + phrase).evidence)

    def test_more_than_dollars_and_ttm_are_not_exact_growth_or_amount(self):
        for metric, unit, value in [('gross_bookings', 'USD', '58000000000'),
                                    ('free_cash_flow', 'USD', '10000000000')]:
            result = self.extract(fact=replace(FACT, metric=metric, unit=unit, value=Decimal(value)))
            self.assertEqual(result.reason_code, 'unsupported_metric_rule')

    def test_arbitrary_qa_reference_without_current_quarter_context_abstains(self):
        self.assertIsNone(self.extract(text=HEADER + QUOTE).evidence)
        self.assertIsNone(self.extract(text=HEADER + PREAMBLE.replace('Q2', 'Q1') + QUOTE).evidence)
        self.assertIsNone(self.extract(text=HEADER + PREAMBLE + 'Not ' + QUOTE).evidence)

    def test_original_quote_erased_changed_or_wrong_value_not_verified(self):
        for text in [HEADER, TEXT.replace('grew 22%', 'grew 23%'), TEXT.replace('grew 22%', 'will grow 22%')]:
            self.assertIsNone(self.extract(text=text).evidence)
        self.assertIsNone(self.extract(fact=replace(FACT, value=Decimal('23'))).evidence)

    def test_header_entity_period_date_and_exact_url_are_required(self):
        for changes, reason in [({'ticker': 'META'}, 'ticker_header_mismatch'),
                                ({'period': 'Q1 2026'}, 'period_header_mismatch'),
                                ({'published_on': date(2026, 8, 6)}, 'date_header_mismatch'),
                                ({'url': URL + '?x=1'}, 'source_not_official')]:
            with self.subTest(changes=changes):
                self.assertEqual(self.extract(asset=replace(ASSET, **changes)).reason_code, reason)
        self.assertEqual(self.extract(fact=replace(FACT, period='Q1 2026')).reason_code, 'period_mismatch')

    def test_unreported_adjusted_wrong_unit_future_and_conflicts_abstain(self):
        for changes in [{'reported': False}, {'adjusted': True}, {'unit': 'USD'}, {'value': Decimal('NaN')}]:
            self.assertIsNone(self.extract(fact=replace(FACT, **changes)).evidence)
        text = HEADER + PREAMBLE + 'Gross bookings grew 22% year-on-year.\n\n' + PREAMBLE + 'Gross bookings grew 19% year-on-year.'
        self.assertEqual(self.extract(text=text).reason_code, 'conflicting_source_values')
        self.assertIsNone(self.extract(asset=replace(ASSET, published_on=date(2027, 8, 5))).evidence)

    def test_registry_bridge_uses_exact_asset_date_not_registry_check_date(self):
        from types import SimpleNamespace
        raw = SimpleNamespace(url=URL, kind='transcript', period='Q2 2026', call_date='2026-08-05')
        entry = SimpleNamespace(ticker='UBER', status='transcripcion_oficial_pdf',
                                assets=(raw,), checked_on='2026-10-22')
        self.assertEqual(asset_from_registry(entry, source_url=URL), ASSET)
        self.assertIsNone(asset_from_registry(entry, source_url=URL + '?x=1'))
        raw.call_date = None
        self.assertIsNone(asset_from_registry(entry, source_url=URL))
        raw.call_date = '2026-08-05'
        entry.status = 'solo_webcast'
        self.assertIsNone(asset_from_registry(entry, source_url=URL))

    def test_tenant_company_scope_and_input_bounds(self):
        for changes in [{'tenant_id': 2}, {'company_id': 9}]:
            with self.assertRaises(ValueError):
                self.extract(fact=replace(FACT, **changes))
        self.assertEqual(self.extract(text='x' * 1_500_001).reason_code, 'invalid_text_size')
        self.assertEqual(self.extract(text=HEADER + 'x' * 301 + QUOTE).evidence, None)


if __name__ == '__main__':
    unittest.main()
