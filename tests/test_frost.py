import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('frost', Path(__file__).parents[1] / 'scripts/frost.py')
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)


class FrostTests(unittest.TestCase):
    def test_projection_deepens_with_cold_and_holds_on_thaw(self):
        days = [{'date': '2027-01-0%d' % i, 'high_mean': -10, 'low_mean': -20} for i in range(1, 4)]
        p = f.project(0.8, days)
        self.assertTrue(p[0]['gel_m'] > 0.8 and p[2]['gel_m'] > p[0]['gel_m'])
        warm = f.project(0.8, [{'date': '2027-03-01', 'high_mean': 8, 'low_mean': 2}])
        self.assertEqual(warm[0]['gel_m'], 0.8)
        self.assertTrue(warm[0]['degel_haut'])

    def test_collect_parses_csv_and_normals(self):
        lines = ['station_id,statio_nom,date_texte,prof_gel,prof_degel']
        for y in (2023, 2024):
            lines += [f'"52",Saint-Georges,{y}-12-15,"0.8","0"', f'"52",Saint-Georges,{y+1}-02-15,"1.6","0"']
        lines += ['"52",Saint-Georges,2026-12-15,"0.5","ND"']
        out = f.collect(lambda url: '\n'.join(lines), dt.date(2026, 12, 17),
                        [{'date': '2026-12-16', 'high_mean': -5, 'low_mean': -15}])
        self.assertEqual((out['station'], out['gel_m'], out['degel_m']), ('Saint-Georges', 0.5, None))
        self.assertEqual(out['normale_m'], 0.8)
        self.assertEqual(out['max_moyen_m'], 1.6)
        self.assertEqual(len(out['projection']), 1)

    def test_fallback_keeps_previous(self):
        def boom(url):
            raise OSError('hors ligne')
        out = f.collect(boom, dt.date(2026, 12, 17), [], {'status': 'ok', 'gel_m': 0.4})
        self.assertEqual((out['status'], out['gel_m']), ('stale', 0.4))


if __name__ == '__main__':
    unittest.main()
