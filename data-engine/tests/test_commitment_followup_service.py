"""Pure deterministic follow-up fixtures, no network, provider or production DB."""
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

from app.services.commitment_followup_service import (
    FollowupCriterion,
    FollowupEvidence,
    evaluate_followup,
    run_followup_batch,
)

TODAY = date(2032, 2, 1)
CRITERION = FollowupCriterion(1, 8, 42, 'revenue', '>=', Decimal('100'), 'USD',
                              '2031-12-31:FY', date(2031, 12, 31), date(2031, 1, 1),
                              date(2031, 12, 31), 'declared_structured')
EVIDENCE = FollowupEvidence(1, 8, 5, 7, 9, 'revenue', Decimal('120'), 'USD',
                            '2031-12-31:FY', date(2031, 12, 31), date(2032, 1, 20),
                            'https://issuer.invalid/filing/2031',
                            '| revenue | 120 | USD | 2031-12-31:FY |',
                            True, False, True, True, TODAY)


class FollowupTests(unittest.TestCase):
    def assess(self, criterion=CRITERION, evidence=(EVIDENCE,), today=TODAY):
        return evaluate_followup(criterion, evidence, today=today)

    def test_reported_result_matches_exact_criterion_with_trace(self):
        result = self.assess()
        self.assertEqual((result.status, result.basis, result.reason_code),
                         ('fulfilled', 'automatic_financial_fact', 'criterion_matched'))
        self.assertEqual(result.provenance, 'system_checked')
        self.assertTrue(result.suggestion_only)
        self.assertEqual(result.evidence[0].chunk_id, 9)
        with self.assertRaises(FrozenInstanceError):
            result.suggestion_only = False

    def test_no_arbitrary_partial_tolerance(self):
        item = replace(EVIDENCE, value=Decimal('99'), excerpt='revenue | 99 | USD | 2031-12-31:FY')
        self.assertEqual(self.assess(evidence=(item,)).status, 'missed')

    def test_all_operators_including_zero_negative_and_decimal(self):
        for op, target, expected in [('>', '120', 'missed'), ('>=', '120', 'fulfilled'),
                                     ('<', '120', 'missed'), ('<=', '120', 'fulfilled'),
                                     ('==', '120', 'fulfilled'), ('>', '-1', 'fulfilled'),
                                     ('>=', '0', 'fulfilled'), ('>=', '120.001', 'missed')]:
            with self.subTest(op=op, target=target):
                result = self.assess(criterion=replace(CRITERION, operator=op, target=Decimal(target)))
                self.assertEqual(result.status, expected)

    def test_overdue_without_data_never_means_missed(self):
        result = self.assess(evidence=())
        self.assertEqual((result.status, result.reason_code), ('insufficient_evidence', 'no_reported_fact'))

    def test_before_and_on_due_date_are_pending_even_with_announcement(self):
        for today in [date(2031, 12, 30), date(2031, 12, 31)]:
            self.assertEqual(self.assess(today=today).status, 'pending')

    def test_forecast_announcement_and_numeric_overlap_do_not_verify(self):
        for item in [replace(EVIDENCE, reported=False),
                     replace(EVIDENCE, excerpt='We expect revenue of 120 USD in 2031-12-31:FY'),
                     replace(EVIDENCE, excerpt='revenue | 120 | USD | 2031-12-31:FY | forecast'),
                     replace(EVIDENCE, primary_source_verified=False),
                     replace(EVIDENCE, quote_verified=False)]:
            with self.subTest(item=item):
                self.assertEqual(self.assess(evidence=(item,)).status, 'insufficient_evidence')

    def test_mismatches_future_and_unsafe_sources_abstain(self):
        cases = [({'unit': 'EUR'}, 'unit_mismatch'), ({'period': '2031-09-30:Q3'}, 'period_mismatch'),
                 ({'metric': 'adjusted_revenue'}, 'ambiguous_metric'), ({'adjusted': True}, 'no_reported_fact'),
                 ({'published_on': date(2033, 1, 1)}, 'future_source'),
                 ({'published_on': date(2030, 1, 1)}, 'future_source'),
                 ({'checked_at': date(2033, 1, 1)}, 'future_source'),
                 ({'source_url': 'https://user:pass@issuer.invalid/filing'}, 'source_not_official'),
                 ({'source_url': 'http://issuer.invalid/filing'}, 'source_not_official'),
                 ({'excerpt': 'revenue | 999 | USD | 2031-12-31:FY'}, 'invalid_quote')]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                result = self.assess(evidence=(replace(EVIDENCE, **changes),))
                self.assertEqual((result.status, result.reason_code), ('insufficient_evidence', reason))

    def test_missing_structured_criterion_or_heuristic_target_is_not_verifiable(self):
        for changes in [{'basis': 'extractor_guess'}, {'metric': None}, {'target': None},
                        {'unit': None}, {'period_end': None}, {'due_on': None},
                        {'operator': '~'}, {'target': Decimal('NaN')}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.assess(criterion=replace(CRITERION, **changes)).status, 'not_verifiable')

    def test_conflicting_restatements_do_not_pick_latest_arbitrarily(self):
        revised = replace(EVIDENCE, value=Decimal('90'), fact_id=6,
                          excerpt='revenue | 90 | USD | 2031-12-31:FY')
        for items in [(EVIDENCE, revised), (revised, EVIDENCE)]:
            result = self.assess(evidence=items)
            self.assertEqual((result.status, result.reason_code), ('insufficient_evidence', 'conflicting_facts'))

    def test_tenant_company_boundaries_and_batch_idempotence(self):
        for changes in [{'tenant_id': 2}, {'company_id': 99}]:
            self.assertEqual(self.assess(evidence=(replace(EVIDENCE, **changes),)).status, 'insufficient_evidence')
        args = dict(tenant_id=1, today=TODAY)
        first = run_followup_batch((CRITERION,), (EVIDENCE,), **args)
        self.assertEqual(first, run_followup_batch((CRITERION,), (EVIDENCE,), **args))
        for criteria, evidence in [((CRITERION,), (replace(EVIDENCE, tenant_id=2),)),
                                    ((replace(CRITERION, tenant_id=2),), (EVIDENCE,)),
                                    ((CRITERION, CRITERION), (EVIDENCE,))]:
            with self.assertRaises(ValueError):
                run_followup_batch(criteria, evidence, **args)

    def test_invalid_dates_and_bounds_fail_closed(self):
        self.assertEqual(self.assess(criterion=replace(CRITERION, promised_on=date(2033, 1, 1))).status, 'not_verifiable')
        with self.assertRaises(ValueError):
            self.assess(criterion=replace(CRITERION, tenant_id=None))
        with self.assertRaises(ValueError):
            run_followup_batch((CRITERION,), (), tenant_id=1, today=TODAY, limit=0)


if __name__ == '__main__':
    unittest.main()
