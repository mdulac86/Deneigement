import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import erable  # noqa: E402


def spring(year, start, n_good=4):
    """Jan-avril froid, puis une série de bonnes journées (nuit -5, jour 6) à partir de `start` (MM-DD)."""
    days, d = {}, dt.date(year, 1, 1)
    s = dt.date.fromisoformat(f'{year}-{start}')
    while d <= dt.date(year, 4, 30):
        days[str(d)] = (-5, 6) if s <= d < s + dt.timedelta(days=n_good) else (-15, -6)
        d += dt.timedelta(days=1)
    return days


class ErableTests(unittest.TestCase):
    def test_first_flow_needs_three_good_days_in_seven(self):
        self.assertEqual(erable.first_flow(spring(2024, '02-20'), 2024), dt.date(2024, 2, 20))
        self.assertIsNone(erable.first_flow(spring(2024, '02-20', n_good=2), 2024))
        self.assertEqual(erable.first_flow(spring(2024, '01-20'), 2024), None)  # redoux de janvier : ne compte pas

    def test_estimate_is_median_of_ten_springs_and_refreshed_each_season(self):
        starts = {2017: '02-18', 2018: '02-14', 2019: '02-04', 2020: '02-22', 2021: '03-17',
                  2022: '02-11', 2023: '02-08', 2024: '02-07', 2025: '02-24', 2026: '02-26'}
        calls = []

        def eccc(url):
            calls.append(url)
            y = int(url.split('LOCAL_YEAR=')[1][:4]); m = int(url.split('LOCAL_MONTH=')[1].split('&')[0])
            data = spring(y, starts[y])
            return {'features': [{'properties': {'LOCAL_DATE': k + ' 00:00:00', 'MIN_TEMPERATURE': v[0], 'MAX_TEMPERATURE': v[1]}}
                                 for k, v in data.items() if int(k[5:7]) == m]}
        est, changed = erable.auto(None, eccc, lambda y, m: [], dt.date(2026, 11, 24))
        self.assertTrue(changed)
        self.assertEqual((est['saison'], est['plus_tot'], est['plus_tard']), (2027, '02-04', '03-17'))
        self.assertEqual(est['estimation'], '02-16')
        n = len(calls)
        same, changed = erable.auto(est, eccc, lambda y, m: [], dt.date(2027, 1, 10))
        self.assertFalse(changed)  # même saison : pas recalculé
        self.assertEqual(len(calls), n)
        _, changed = erable.auto(est, eccc, lambda y, m: [], dt.date(2027, 9, 15))
        self.assertTrue(changed)  # automne suivant : saison 2028

    def test_manual_estimate_only_for_its_season(self):
        cfg = {'premiere_coulee': {'manuelle': {'saison': 2027, 'date': '02-18', 'raison': 'El Niño'}}}
        est = {'saison': 2027, 'estimation': '02-16', 'plus_tot': '02-04', 'plus_tard': '03-17', 'annees': {'2017': '02-18', '2026': '02-26'}}
        e = erable.merge(cfg, est, dt.date(2026, 11, 24))
        self.assertEqual(e['premiere_coulee']['estimation'], '02-18')
        self.assertIn('El Niño', ' '.join(e['raisons']))
        est28 = {**est, 'saison': 2028, 'estimation': '02-15'}
        e = erable.merge(cfg, est28, dt.date(2027, 10, 1))
        self.assertEqual(e['premiere_coulee']['estimation'], '02-15')  # l'estimation manuelle 2027 ne s'applique plus
        self.assertNotIn('El Niño', ' '.join(e['raisons']))


if __name__ == '__main__':
    unittest.main()
