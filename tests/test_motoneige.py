import datetime as dt
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import motoneige as mo  # noqa: E402

TZ = ZoneInfo('America/Toronto')
START = dt.datetime(2027, 1, 18, 1, tzinfo=dt.timezone.utc)  # lundi 20 h (heure locale) la veille


def windows(spec):
    """spec : [(neige cm, précip mm, température, rafales km/h)] par tranche de 6 h."""
    return [{'debut': (START + dt.timedelta(hours=6 * i)).isoformat(), 'fin': (START + dt.timedelta(hours=6 * i + 6)).isoformat(),
             'snow_cm': s, 'precip_mm': p, 'temp': t, 'gust_kmh': g} for i, (s, p, t, g) in enumerate(spec)]


def day(days, iso):
    return next(d for d in days if d['date'] == iso)


class MotoneigeTests(unittest.TestCase):
    def test_powder_after_fresh_snow_on_a_good_base(self):
        spec = [(0, 0, -12, 10)] * 4 + [(8, 8, -10, 20), (8, 8, -10, 20)] + [(0, 0, -12, 10)] * 8
        d = day(mo.days_for(60, windows(spec), TZ), '2027-01-19')
        self.assertEqual(d['surface'], 'Poudreuse')
        self.assertGreaterEqual(d['base_cm'], 70)  # 60 + 16 cm tassés à 80 %
        self.assertEqual(d['note'], 9)  # base 5 + poudreuse 4

    def test_thaw_then_freeze_makes_crust(self):
        spec = [(0, 4, 3, 10)] * 4 + [(0, 0, -8, 10)] * 8
        d = day(mo.days_for(50, windows(spec), TZ), '2027-01-19')
        self.assertEqual(d['surface'], 'Croûte / glacée')
        self.assertLess(d['base_cm'], 50)  # fonte et pluie
        self.assertLessEqual(d['note'], 3)

    def test_thin_base_is_capped_and_no_snow_is_zero(self):
        spec = [(6, 6, -10, 10)] * 2 + [(0, 0, -10, 10)] * 8
        d = day(mo.days_for(2, windows(spec), TZ), '2027-01-18')
        self.assertLessEqual(d['note'], 2)  # 2 cm + neige fraîche : roches et souches
        none = mo.days_for(0, windows([(0, 0, -5, 10)] * 8), TZ)
        self.assertTrue(all(x['surface'] == 'Pas de neige' and x['note'] == 0 for x in none))

    def test_rain_and_warm_day(self):
        spec = [(0, 0, -5, 10)] * 6 + [(0, 3, 4, 10), (0, 3, 5, 10)] + [(0, 0, 2, 10)] * 4
        d = day(mo.days_for(60, windows(spec), TZ), '2027-01-19')
        self.assertEqual(d['surface'], 'Lourde (redoux)')
        self.assertGreater(d['pluie_mm'], 2)

    def test_worth_the_drive_and_weekend(self):
        self.assertEqual(mo.worth(8, 60), 8)
        self.assertEqual(mo.worth(8, 324), 3.6)  # Monts Valins : 5 h 24
        days = [{'date': str(dt.date(2027, 1, 18) + dt.timedelta(days=i)), 'note': i} for i in range(7)]
        self.assertEqual([d['date'] for d in mo.weekend(days, dt.date(2027, 1, 20))], ['2027-01-23', '2027-01-24'])
        self.assertTrue(mo.in_season({'saison': {'debut': '11-15', 'fin': '04-30'}}, dt.date(2027, 2, 1)))
        self.assertFalse(mo.in_season({'saison': {'debut': '11-15', 'fin': '04-30'}}, dt.date(2027, 7, 1)))

    def test_change_over_72h_from_history(self):
        now = dt.datetime(2027, 1, 20, 12, tzinfo=dt.timezone.utc)
        hist = [{'time': (now - dt.timedelta(hours=72)).isoformat(), 'cm': {'jackman': 40}},
                {'time': (now - dt.timedelta(hours=24)).isoformat(), 'cm': {'jackman': 55}}]
        self.assertEqual(mo.change_72h(hist, 'jackman', 52, now), 12)
        self.assertIsNone(mo.change_72h(hist, 'zec-jaro', 30, now))


if __name__ == '__main__':
    unittest.main()
