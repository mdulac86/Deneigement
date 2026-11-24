import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('noaa', Path(__file__).parents[1] / 'scripts/noaa.py')
noaa = importlib.util.module_from_spec(spec); spec.loader.exec_module(noaa)

RUN = dt.datetime(2026, 12, 1, 9, tzinfo=dt.timezone.utc)


def idx(keys):
    return '\n'.join(f'{i + 1}:{i * 1000}:d=2026120109:{k}:' for i, k in enumerate(keys)).encode()


class NoaaTests(unittest.TestCase):
    def test_index_keeps_probability_threshold(self):
        with mock.patch.object(noaa.grib, 'get', return_value=idx(['ASNOW:surface:6-12 hour acc fcst',
                                                                   'ASNOW:surface:6-12 hour acc fcst:prob >0.0508:prob fcst 255/255'])):
            rows = noaa.index('u')
        self.assertIsNotNone(noaa.pick(rows, 'ASNOW:surface:6-12 hour acc fcst:prob >0.0508:prob fcst 255/255'))
        self.assertEqual(rows[0]['_length'], 1000)

    def test_nbm_windows_end_on_synoptic_hours(self):
        """Run de 09 UTC : la première tranche de 6 h va de 12 à 18 UTC (échéance f009)."""
        seen = []

        def fake_get(url, byte_range=None, tries=6):
            if url.endswith('.idx'):
                f = int(url.split('.f')[-1][:3])
                seen.append(f)
                w = f'{f - 6}-{f} hour acc fcst'
                return idx([f'ASNOW:surface:{w}', f'APCP:surface:{w}', f'TMP:2 m above ground:{f} hour fcst',
                            f'ASNOW:surface:{w}:prob >0.0254:prob fcst 255/255', f'ASNOW:surface:{w}:prob >0.0508:prob fcst 255/255'])
            return b''

        def fake_field(url, entry, lat, lon, units=False):
            k = entry['key']
            v = 0.06 if k.startswith('ASNOW') and 'prob' not in k else 3.0 if k.startswith('APCP') else 270.15 if k.startswith('TMP') else 40.0
            return (v, 'm' if k.startswith('ASNOW') and 'prob' not in k else 'K') if units else v

        with mock.patch.object(noaa.grib, 'get', side_effect=fake_get), mock.patch.object(noaa.grib, 'field', side_effect=fake_field), \
                mock.patch.object(noaa.grib, 'warmup'), mock.patch.object(noaa, 'nbm_run', return_value=RUN):
            out = noaa.nbm(46.2, -70.5, RUN)
        self.assertEqual(min(seen), 9)
        self.assertTrue(all((9 + f) % 6 == 0 for f in seen))
        first = out['tranches'][0]
        self.assertEqual((first['debut'], first['fin']), ('2026-12-01T12:00:00Z', '2026-12-01T18:00:00Z'))
        self.assertEqual((first['snow_cm'], first['p_5cm'], first['temp']), (6.0, 40, -3.0))
        self.assertIsNone(out['tranches'][-1]['p_5cm'])  # probabilités seulement jusqu'à 48 h
        self.assertEqual(out['hours'][0]['snow_cm'], 1.0)  # 6 cm répartis sur 6 h

    def test_hrrr_day_keys_and_differences(self):
        def fake_get(url, byte_range=None, tries=6):
            f = int(url.split('wrfsfcf')[-1][:2])
            acc = f'0-{f // 24} day acc fcst' if f % 24 == 0 else f'0-{f} hour acc fcst'
            return idx([f'ASNOW:surface:{acc}', f'APCP:surface:{acc}', f'TMP:2 m above ground:{f} hour fcst', f'CFRZR:surface:{f} hour fcst'])

        def fake_field(url, entry, lat, lon, units=False):
            f = int(url.split('wrfsfcf')[-1][:2])
            k = entry['key']
            v = f * 0.01 if k.startswith('ASNOW') else f * 1.0 if k.startswith('APCP') else 272.15 if k.startswith('TMP') else float(f == 30)
            return (v, 'm') if units else v

        with mock.patch.object(noaa.grib, 'get', side_effect=fake_get), mock.patch.object(noaa.grib, 'field', side_effect=fake_field), \
                mock.patch.object(noaa.grib, 'warmup'), mock.patch.object(noaa, 'hrrr_run', return_value=RUN):
            out = noaa.hrrr(46.2, -70.5, RUN)
        self.assertEqual(len(out['hours']), 48)
        self.assertTrue(all(h['snow_cm'] == 1.0 for h in out['hours']))  # 1 cm/h, y compris à 24 h et 48 h
        self.assertEqual(sum(h['verglas'] for h in out['hours']), 3)  # tranche de 3 h finissant à f030


if __name__ == '__main__':
    unittest.main()
