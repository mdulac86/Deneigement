import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / f'scripts/{name}.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


v = load('verify')
h = load('history')


class VerifyTests(unittest.TestCase):
    def test_score_counts_storms_and_errors(self):
        pairs = {'2026-01-01': (6, 8), '2026-01-02': (0, 7), '2026-01-03': (5, 1), '2026-01-04': (0, 0)}
        s = v.score(pairs)
        self.assertEqual(s['tempetes'], {'detectees': 1, 'manquees': 1, 'fausses_alertes': 1})
        self.assertEqual(s['jours_neige'], 3)
        self.assertEqual(s['ecart_moyen_cm'], round((2 + 7 + 4) / 3, 1))
        self.assertEqual(s['biais_cm'], round((-2 - 7 + 4) / 3, 1))

    def test_ranking_best_first(self):
        r = v.ranked({'a': {'d': (10, 0)}, 'b': {'d': (1, 2)}}, {'a': 'A', 'b': 'B'})
        self.assertEqual([x['id'] for x in r], ['b', 'a'])

    def test_live_uses_last_snapshot_before_midnight(self):
        d = Path(tempfile.mkdtemp())
        day = dt.date(2026, 11, 12)
        hours = [{'time': (dt.datetime(2026, 11, 12, 5, tzinfo=dt.timezone.utc) + dt.timedelta(hours=i)).isoformat(), 'snow_cm': 0.5} for i in range(24)]
        early = {'sources': [{'id': 'mm', 'status': 'ok', 'days': [{'date': '2026-11-12', 'snow_cm': [0, 2]}]}], 'models': []}
        late = {'sources': [{'id': 'mm', 'status': 'ok', 'days': [{'date': '2026-11-12', 'snow_cm': [4, 6]}]}],
                'models': [{'id': 'hrdps', 'status': 'ok', 'hours': hours}], 'hourly_snow': hours}
        after = {'sources': [{'id': 'mm', 'status': 'ok', 'days': [{'date': '2026-11-12', 'snow_cm': [20, 20]}]}]}
        for folder, name, content in (('2026-11-11', '12', early), ('2026-11-11', '23', late), ('2026-11-12', '06', after)):
            (d / 'archive' / folder).mkdir(parents=True, exist_ok=True)
            (d / 'archive' / folder / f'{name}.json').write_text(json.dumps(content))
        with patch.object(v, 'DATA', d):
            out = v.live_forecasts(day)
        self.assertEqual(out['mm'], 5)
        self.assertEqual(out['hrdps'], 12)
        self.assertEqual(out['consensus'], 12)


class HistoryTests(unittest.TestCase):
    def test_ecmwf_difference_of_accumulations(self):
        idx = [{'param': 'tp', '_offset': 0, '_length': 1}, {'param': 'sf', '_offset': 1, '_length': 1}]
        values = {('tp', 30): 0.002, ('sf', 30): 0.001, ('tp', 54): 0.010, ('sf', 54): 0.007}
        calls = []

        def field(url, entry, lat, lon, units=False):
            step = 30 if '-30h-' in url else 54
            calls.append(url)
            return values[(entry['param'], step)], 'm'
        with patch.object(h.grib, 'ecmwf_index', return_value=idx), patch.object(h.grib, 'field', side_effect=field):
            r = h.ecmwf_day(dt.date(2026, 1, 10), 'ifs')
        self.assertEqual((r['tp_mm'], r['snow_cm']), (8.0, 6.0))
        self.assertIn('/20260109/00z/ifs/', calls[0])

    def test_gfs_buckets_and_temperature(self):
        def idx(url):
            step = int(url.split('.f')[-1][:3])
            return [{'var': 'TMP', 'level': '2 m above ground', 'desc': f'{step} hour fcst', 'step': step, 'kind': 't', '_offset': 0, '_length': 1},
                    {'var': 'APCP', 'level': 'surface', 'desc': f'{step-6}-{step} hour acc fcst', 'step': step, 'kind': 'p', '_offset': 1, '_length': 1}]

        def field(url, entry, lat, lon, units=False):
            return 268.15 if entry['kind'] == 't' else 2.0  # -5 °C, 2 mm par tranche de 6 h
        with patch.object(h.grib, 'ncep_index', side_effect=idx), patch.object(h.grib, 'field', side_effect=field):
            r = h.gfs_day(dt.date(2026, 1, 10))
        self.assertEqual((r['tp_mm'], r['snow_cm']), (8.0, 10.4))

    def test_aifs_units_and_missing_sf(self):
        idx = [{'param': 'tp', '_offset': 0, '_length': 1}, {'param': '2t', '_offset': 1, '_length': 1}]
        def field(url, entry, lat, lon, units=False):
            step = 30 if '-30h-' in url else 54
            return ({'tp': 2.0 if step == 30 else 10.0, '2t': 268.15}[entry['param']], 'kg m**-2' if entry['param'] == 'tp' else 'K')
        with patch.object(h.grib, 'ecmwf_index', return_value=idx), patch.object(h.grib, 'field', side_effect=field):
            r = h.ecmwf_day(dt.date(2026, 1, 10), 'aifs-single')
        self.assertEqual(r['tp_mm'], 8.0)  # kg m-2 = mm, pas de x1000
        self.assertEqual(r['snow_cm'], 10.4)  # estimée à -5 °C
        self.assertIn('estimée', r['calcul'])

    def test_stale_reruns_old_versions(self):
        fc = {'ifs': {'snow_cm': 1}, 'aifs': {'snow_cm': 900}, 'gfs': {'error': 'x'}}
        self.assertEqual(h.stale(fc), ['aifs', 'gfs'])


if __name__ == '__main__':
    unittest.main()
