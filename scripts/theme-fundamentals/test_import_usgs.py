import importlib.util
from pathlib import Path
import json
import unittest

spec = importlib.util.spec_from_file_location('usgs', Path(__file__).with_name('import_usgs.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class USGSUnits(unittest.TestCase):
    def test_missing_and_zero(self):
        self.assertIsNone(m.number('W'))
        self.assertIsNone(m.number('NA'))
        self.assertEqual(m.number('0'), 0)
        self.assertEqual(m.number('1,000'), 1000)

    def test_invalid(self):
        for bad in ('NaN', '-1', 'inf'):
            with self.assertRaises(ValueError):
                m.number(bad)

    def test_snapshot(self):
        d = json.loads(Path('data/theme-fundamentals/materiales.json').read_text())
        self.assertTrue(all(s['source'] and s['vintage'] and s['published'] for s in d['series'] if not s.get('monthly')))
        lithium = next(s for s in d['series'] if s['title'].startswith('Litio'))
        self.assertIsNone(next(r for r in lithium['rows'] if r['label'] == 'Estados Unidos')['values'][0])
        reliance = d['series'][-1]
        self.assertEqual(next(r for r in reliance['rows'] if r['label'] == 'Litio')['values'][0], '>50')
        self.assertTrue(all(s['kind'] == 'estimacion_oficial' for s in d['series'] if not s.get('monthly')))


if __name__ == '__main__':
    unittest.main()
