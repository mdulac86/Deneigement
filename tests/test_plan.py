import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('plan', Path(__file__).parents[1] / 'scripts/plan.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
TZ = ZoneInfo('America/Toronto')


def series(start, rates, spread=0.0, n=3):
    """rates : cm/h à partir de start (datetime local)."""
    return [{'time': start + dt.timedelta(hours=i), 'snow_cm': r, 'lo': max(0, r - spread), 'hi': r + spread, 'n': n}
            for i, r in enumerate(rates)]


def at(day, h, m=0):
    return dt.datetime(2026, 11, day, h, m, tzinfo=TZ)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.cfg = p.load_config()
        self.now = at(10, 12)  # mardi midi

    def plan(self, hours):
        return p.build_plan(hours, self.cfg, self.now)

    def test_duration_rule(self):
        self.assertEqual(p.duration_h(6, self.cfg), 4)
        self.assertEqual(p.duration_h(10, self.cfg), 4)
        self.assertEqual(p.duration_h(15, self.cfg), 5.5)
        self.assertEqual(p.duration_h(20, self.cfg), 5.5)
        self.assertEqual(p.duration_h(25, self.cfg), 7)

    def test_early_storm_leaves_for_745(self):
        # Mercredi : 2 cm/h de 22 h à 1 h -> 6 cm, 4 h de tournée pour 7 h 45 -> départ 3 h 30.
        q = self.plan(series(at(10, 22), [2, 2, 2]))[0]
        self.assertEqual(q['statut'], 'sortie')
        self.assertEqual(q['mode'], 'matin')
        self.assertEqual(q['echeance'], at(11, 7, 45).isoformat())
        self.assertEqual(q['depart'], at(11, 3, 30).isoformat())
        self.assertIsNone(q['final'])

    def test_late_threshold_goes_at_five(self):
        # 5 cm atteints vers 4 h 30 -> départ 5 h, tournée finie 9 h (retard noté).
        q = self.plan(series(at(11, 0), [0.5, 0.5, 1, 1, 2, 2, 1]))[0]
        self.assertEqual(q['depart'], at(11, 5).isoformat())
        self.assertTrue(any('après l’échéance' in n for n in q['notes']))

    def test_final_after_breakfast_or_nine(self):
        # 5 cm à 1 h, puis 0,4 cm/h jusqu'à 7 h -> départ 3 h 30, final 9 h.
        q = self.plan(series(at(10, 23), [2.5, 2.5] + [0.4] * 6))[0]
        self.assertEqual(q['depart'], at(11, 3, 30).isoformat())
        self.assertEqual(q['final']['heure'], at(11, 9).isoformat())
        self.assertEqual(q['final']['type'], 'nettoyage_final')
        # Fin à 8 h -> on attend 9 h.
        q = self.plan(series(at(10, 23), [2.5, 2.5] + [0.4] * 7))[0]
        self.assertEqual(q['final']['heure'], at(11, 9).isoformat())
        # Fin à 10 h -> nettoyage à la fin.
        q = self.plan(series(at(10, 23), [2.5, 2.5] + [0.4] * 9))[0]
        self.assertEqual(q['final']['heure'], at(11, 10).isoformat())
        # Beaucoup de neige après le départ -> 2e tournée.
        q = self.plan(series(at(10, 23), [2.5, 2.5] + [1.5] * 6))[0]
        self.assertEqual(q['final']['type'], 'deuxieme_tournee')

    def test_crew_still_out_pushes_final(self):
        # 1 cm/h de 23 h à 7 h : 5 cm à 4 h, tournée jusqu'à 8 h -> final 9 h.
        q = self.plan(series(at(10, 23), [1] * 8))[0]
        self.assertEqual(q['depart'], at(11, 4).isoformat())
        self.assertEqual(q['final']['heure'], at(11, 9).isoformat())

    def test_big_storm_leaves_earlier(self):
        # 15 cm -> 5,5 h -> départ 2 h pour 7 h 45.
        q = self.plan(series(at(10, 21), [1.5] * 10))[0]
        self.assertEqual(q['duree_h'], 5.5)
        self.assertEqual(q['depart'], at(11, 2).isoformat())

    def test_weekend_deadline_and_note(self):
        # Samedi 14 nov. : 2 cm/h de 0 h à 4 h -> échéance 7 h 45, 4 h -> départ 3 h 30.
        q = self.plan(series(at(14, 0), [2] * 4))[0]
        self.assertTrue(q['fin_de_semaine'])
        self.assertEqual(q['echeance'], at(14, 7, 45).isoformat())
        self.assertEqual(q['depart'], at(14, 3, 30).isoformat())
        self.assertTrue(any('acte de présence' in n for n in q['notes']))

    def test_daytime_storm_goes_at_threshold(self):
        q = self.plan(series(at(10, 13), [1] * 8))[0]
        self.assertEqual(q['mode'], 'jour')
        self.assertEqual(q['depart'], at(10, 18).isoformat())

    def test_below_threshold_and_possible(self):
        q = self.plan(series(at(10, 22), [0.5] * 6))[0]
        self.assertEqual(q['statut'], 'sous_seuil')
        q = self.plan(series(at(10, 22), [0.6] * 6, spread=0.4))[0]
        self.assertEqual(q['statut'], 'possible')

    def test_short_break_keeps_one_event(self):
        rates = [2, 2, 0, 0, 0, 2, 2]
        self.assertEqual(len(p.events(series(at(10, 22), rates), self.cfg)), 1)
        rates = [2, 2, 0, 0, 0, 0, 0, 2, 2]
        self.assertEqual(len(p.events(series(at(10, 22), rates), self.cfg)), 2)

    def test_small_snowfalls_add_up(self):
        # Trois chutes de 2 cm (mardi soir, mercredi soir, jeudi soir) : 5 cm atteints jeudi soir.
        hours = series(at(10, 20), [1, 1]) + series(at(11, 20), [1, 1]) + series(at(12, 20), [1, 1])
        out = self.plan(hours)
        self.assertEqual([p['statut'] for p in out], ['sous_seuil', 'sous_seuil', 'sortie'])
        self.assertEqual(out[1]['au_sol_apres_cm'], 4)
        self.assertEqual(out[2]['deja_au_sol_cm'], 4)
        self.assertEqual(out[2]['seuil_atteint'], at(12, 21).isoformat())
        self.assertTrue(any('déjà accumulés' in n for n in out[2]['notes']))

    def test_carry_from_previous_days_and_melt_reset(self):
        q = p.build_plan(series(at(10, 22), [1.5, 1.5]), self.cfg, self.now, carry=2.5)[0]
        self.assertEqual(q['statut'], 'sortie')  # 2,5 + 3 cm
        hours = series(at(10, 20), [1, 1]) + series(at(12, 20), [1, 1, 1])
        out = p.build_plan(hours, self.cfg, self.now, melt_days=['2026-11-11'])
        self.assertEqual(out[-1]['statut'], 'sous_seuil')  # redoux mercredi : on repart de zéro

    def test_carry_from_records(self):
        r = lambda d, s, rain=0, tx=-5: {'date': f'2026-12-{d:02d}', 'snow_cm': s, 'rain_mm': rain, 'tmax': tx}
        self.assertEqual(p.carry_from_records([r(1, 2), r(2, 0), r(3, 0), r(4, 0), r(5, 1.5)], self.cfg), 3.5)
        self.assertEqual(p.carry_from_records([r(1, 2), r(2, 0, tx=6), r(3, 1)], self.cfg), 1)
        self.assertEqual(p.carry_from_records([r(1, 3), r(2, 3), r(3, 1)], self.cfg), 1)

    def test_hourly_consensus_median_and_missing(self):
        s = [{'id': 'a', 'hours': [{'time': '2026-11-11T05:00:00Z', 'snow_cm': 1}]},
             {'id': 'b', 'hours': [{'time': '2026-11-11T05:00:00Z', 'snow_cm': 3}]},
             {'id': 'c', 'hours': [{'time': '2026-11-11T05:00:00Z', 'snow_cm': None}]}]
        h = p.hourly_consensus(s, TZ)[0]
        self.assertEqual((h['snow_cm'], h['lo'], h['hi'], h['n']), (2, 1, 3, 2))
        self.assertEqual(h['time'], at(11, 0))


if __name__ == '__main__':
    unittest.main()
