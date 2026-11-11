import datetime as dt
import re
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import ecmwf  # noqa: E402

TZ = ZoneInfo('America/Toronto')
RUN = dt.datetime(2026, 11, 11, 0, tzinfo=dt.timezone.utc)


class EcmwfTests(unittest.TestCase):
    def test_runs_are_00_and_12(self):
        r = list(ecmwf.runs(dt.datetime(2026, 11, 11, 15, 30, tzinfo=dt.timezone.utc)))
        self.assertEqual([x.hour for x in r], [12, 0, 12, 0])

    def test_day_windows_align_on_06utc(self):
        w = ecmwf.day_windows(RUN, TZ)
        self.assertEqual(w[0], (dt.date(2026, 11, 11), 6, 30))
        self.assertEqual(w[1], (dt.date(2026, 11, 12), 30, 54))
        w12 = ecmwf.day_windows(RUN + dt.timedelta(hours=12), TZ)
        self.assertEqual(w12[0], (dt.date(2026, 11, 12), 18, 42))

    def test_deterministic_rates_from_accumulations(self):
        def field(url, entry, lat, lon):
            step = int(re.search(r'-(\d+)h-', url)[1])
            return {'tp': step * 0.0002, 'sf': step * 0.0001, '2t': 270.15}[entry['param']]
        idx = [{'param': p, '_offset': 0, '_length': 1} for p in ('tp', 'sf', '2t')]
        with patch.object(ecmwf, 'latest_run', return_value=(RUN, 'x')), \
             patch.object(ecmwf.grib, 'ecmwf_index', return_value=idx), patch.object(ecmwf.grib, 'field', side_effect=field):
            r = ecmwf.deterministic(46.2, -70.5, RUN)
        self.assertEqual(len(r['hours']), 72)
        self.assertEqual(r['hours'][0]['snow_cm'], 0.1)  # 0,1 mm d'eau par heure
        self.assertEqual(r['hours'][0]['precip_mm'], 0.2)
        self.assertEqual(r['hours'][0]['temp'], -3.0)

    def test_ensemble_probability(self):
        # 51 membres : membre n donne n/5 cm sur chaque fenêtre de 24 h -> 26 membres (25..50) >= 5 cm.
        def idx(url):
            return [{'param': 'sf', 'number': str(n), '_offset': 0, '_length': 1} for n in range(51)]

        def field(url, entry, lat, lon):
            step = int(re.search(r'-(\d+)h-', url)[1])
            return int(entry['number']) / 5 / 1000 * (step - 6) / 24
        with patch.object(ecmwf, 'latest_run', return_value=(RUN, 'x')), \
             patch.object(ecmwf.grib, 'ecmwf_index', side_effect=idx), patch.object(ecmwf.grib, 'field', side_effect=field):
            r = ecmwf.ensemble(46.2, -70.5, RUN, TZ)
        d = r['jours'][0]
        self.assertEqual(d['membres'], 51)
        self.assertEqual(d['prob_5cm'], round(100 * 26 / 51))
        self.assertEqual(d['p50_cm'], 5.0)


if __name__ == '__main__':
    unittest.main()
