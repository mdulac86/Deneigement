import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import snowdepth  # noqa: E402

NOW = dt.datetime(2026, 12, 10, 12, tzinfo=dt.timezone.utc)


def feat(t, depth, temp=-2.0):
    return {'properties': {'date_tm-value': t, 'avg_snw_dpth_pst5mts': depth, 'air_temp': temp}}


class SnowDepthTests(unittest.TestCase):
    def test_hourly_keeps_closest_to_hour_and_ignores_negative(self):
        s = snowdepth.hourly([feat('2026-12-10T10:38:00.000Z', 30), feat('2026-12-10T10:01:00.000Z', 31),
                              feat('2026-12-10T11:00:00.000Z', -1)])
        self.assertEqual([x['depth_cm'] for x in s], [31, None])

    def test_change_24h_shows_melt(self):
        series = [{'time': (NOW - dt.timedelta(hours=h)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'depth_cm': 40 - (24 - h) * 0.5, 'temp': 3}
                  for h in range(24, -1, -1)]
        self.assertEqual(snowdepth.change(series), -12)

    def test_station_unavailable_is_reported(self):
        def broken(url, json_data=False):
            raise OSError('refusé')
        out = snowdepth.collect(broken, NOW)
        self.assertTrue(all(s['status'] == 'unavailable' for s in out['stations']))
        self.assertEqual(out['stations'][0]['km'], 38)


if __name__ == '__main__':
    unittest.main()
