import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('eia', Path(__file__).with_name('import_eia.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class EIAUnits(unittest.TestCase):
    def test_withheld_missing_and_zero(self):
        for marker in ('W', '-', '--', '.', None):
            self.assertIsNone(m.number(marker))
        self.assertEqual(m.number(0), 0)
        self.assertEqual(m.number(1000, 1000), 1)

    def test_invalid(self):
        for invalid in ('NaN', 'inf', -1):
            with self.assertRaises(ValueError):
                m.number(invalid)

    def test_checked_snapshot(self):
        import json
        d = json.loads(Path('data/theme-fundamentals/nuclear.json').read_text())
        coverage = next(s for s in d['series'] if s['title'].startswith('Cobertura'))
        self.assertEqual(coverage['rows'][0]['values'][:2], [None, None])
        self.assertEqual(coverage['vintage'], '31/12/2025')
        self.assertTrue(all(s['source'].startswith('https://') and s['published'] and s['vintage'] for s in d['series']))
        self.assertEqual(d['series'][-1]['kind'], 'escenario')


if __name__ == '__main__':
    unittest.main()
