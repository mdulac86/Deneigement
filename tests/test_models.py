import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest
import urllib.parse

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('models', Path(__file__).parents[1] / 'scripts/models.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
NOW = dt.datetime(2026, 11, 10, 12, tzinfo=dt.timezone.utc)

CAPS = '''<?xml version="1.0"?><WMS_Capabilities xmlns="http://www.opengis.net/wms"><Capability><Layer><Layer>
<Name>{name}</Name><Dimension name="time" units="ISO8601">2026-11-10T12:00:00Z/2026-11-11T00:00:00Z/PT1H</Dimension>
<Dimension name="reference_time" units="ISO8601" default="2026-11-10T06:00:00Z">2026-11-10T06:00:00Z</Dimension>
</Layer></Layer></Capability></WMS_Capabilities>'''


def fake_geomet(url, json_data=False):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    if q['request'] == 'GetCapabilities':
        if q['layer'].startswith('RDPS.ETA'):
            raise OSError('400')
        return CAPS.format(name=q['layer'])
    t = m.utc(q['time'])
    h = (t - NOW).total_seconds() / 3600
    value = h * 1.0 if q['layers'].endswith('_PR') else -3.0  # 1 mm/h à -3 °C
    return {'type': 'FeatureCollection', 'features': [{'properties': {'value': value}}]}


class ModelTests(unittest.TestCase):
    def test_snow_ratio(self):
        self.assertEqual(m.snow_from_precip(1, -1), 1.0)
        self.assertEqual(m.snow_from_precip(1, -5), 1.3)
        self.assertEqual(m.snow_from_precip(1, 3), 0.0)
        self.assertIsNone(m.snow_from_precip(None, -5))
        self.assertTrue(0 < m.snow_from_precip(1, 1) < 1)

    def test_geomet_accumulation_differences_and_fallback_layer(self):
        r = m.eccc_model('rdps', fake_geomet, 46.2, -70.5, NOW)
        self.assertEqual(r['layers'], ['RDPS.CONTINENTAL_PR', 'RDPS.CONTINENTAL_TT'])
        self.assertEqual(len(r['hours']), 12)
        self.assertTrue(all(h['precip_mm'] == 1.0 and h['snow_cm'] == 1.3 for h in r['hours']))

    def test_gfs_csv(self):
        def fake(url, json_data=False):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            var = q['var']
            unit = 'K' if var.startswith('Temp') else 'kg.m-2.s-1'
            rows = [f'time,latitude[unit="degrees_north"],longitude[unit="degrees_east"],{var}[unit="{unit}"]']
            for i in range(10):
                t = m.zulu(NOW + dt.timedelta(hours=i))
                rows.append(f'{t},46.2,289.5,{271.15 if unit == "K" else 1/3600}')
            return '\n'.join(rows)
        r = m.gfs_model(fake, 46.2, -70.5, NOW)
        self.assertEqual(len(r['hours']), 9)
        self.assertEqual(r['hours'][0]['temp'], -2.0)
        self.assertEqual(r['hours'][0]['snow_cm'], 1.3)

    def test_met_six_hour_steps_are_spread(self):
        met = {'hourly': [{'time': '2026-11-12T00:00:00Z', 'temp': -1, 'precip_mm': 6},
                          {'time': '2026-11-12T06:00:00Z', 'temp': -1, 'precip_mm': None}]}
        r = m.met_model(met)
        self.assertEqual(len(r['hours']), 6)
        self.assertEqual(r['hours'][0]['snow_cm'], 1.0)

    def test_failed_model_is_unavailable_not_zero(self):
        def broken(url, json_data=False):
            raise OSError('refusé')
        out = {x['id']: x for x in m.collect_models(broken, {}, 46.2, -70.5, NOW)}
        self.assertEqual(out['hrdps']['status'], 'unavailable')
        self.assertEqual(out['hrdps']['hours'], [])


if __name__ == '__main__':
    unittest.main()
