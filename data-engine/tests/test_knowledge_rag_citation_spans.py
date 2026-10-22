"""Verificacion literal sin normalizacion silenciosa de offsets Python."""
from __future__ import annotations

import unittest

from app.services.knowledge_rag.citations import verify_citation
from app.services.knowledge_rag.domain import sha256_hex


class CitationSpanTests(unittest.TestCase):
    def verify(self, quote, parent, start, end):
        return verify_citation(
            quote=quote, parent_text=parent, char_start=start, char_end=end,
            text_sha256=sha256_hex(quote),
        )

    def test_valid_literal_spans_include_unicode_and_boundaries(self):
        for parent, start, end, quote in [
            ('abc', 0, 3, 'abc'), ('abcdef', 3, 6, 'def'),
            ('Ingresos: 3 €', 10, 13, '3 €'),
        ]:
            with self.subTest(start=start, end=end, quote=quote):
                result = self.verify(quote, parent, start, end)
                self.assertTrue(result.ok)
                self.assertIn('quote_matches_parent_span', result.checks)

    def test_invalid_offsets_never_pass_via_slice_normalization(self):
        for parent, start, end, quote in [
            ('abcdef', -3, 6, 'def'), ('abc', 0, 99, 'abc'),
            ('abc', 3, 2, ''), ('abc', 1, 1, ''),
            ('abc', True, 3, 'bc'), ('abc', 0, False, ''),
            ('abc', 0.0, 3, 'abc'), ('abc', '0', 3, 'abc'),
            ('abc', 0, None, 'abc'), ('', 0, 0, ''),
        ]:
            with self.subTest(start=start, end=end, quote=quote):
                result = self.verify(quote, parent, start, end)
                self.assertFalse(result.ok)
                self.assertIn('invalid_quote_span', result.failures)
                self.assertNotIn('quote_matches_parent_span', result.checks)

    def test_blank_quote_is_not_evidence_even_with_matching_hash(self):
        result = self.verify('  ', 'a  b', 1, 3)
        self.assertFalse(result.ok)
        self.assertIn('empty_quote', result.failures)

    def test_literal_and_hash_checks_still_fail_independently(self):
        result = self.verify('xyz', 'abc', 0, 3)
        self.assertFalse(result.ok)
        self.assertIn('quote_not_in_parent_span', result.failures)
        self.assertIn('quote_hash', result.checks)
        result = verify_citation(quote='abc', parent_text='abc', char_start=0, char_end=3,
                                 text_sha256='wrong')
        self.assertFalse(result.ok)
        self.assertIn('quote_hash_mismatch', result.failures)


if __name__ == '__main__':
    unittest.main()
