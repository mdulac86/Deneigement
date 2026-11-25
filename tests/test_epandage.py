import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('epandage', Path(__file__).parents[1] / 'scripts/epandage.py')
e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e)
TZ = ZoneInfo('America/Toronto')


def at(day, h, m=0):
    return dt.datetime(2026, 12, day, h, m, tzinfo=TZ)


def models(start, temps, rains, snows=None, ids=('gfs', 'ifs', 'aifs')):
    """Mêmes heures pour chaque modèle (temp °C, pluie mm, neige cm) à partir de start."""
    snows = snows or [0] * len(temps)
    hours = [{'time': (start + dt.timedelta(hours=i)).isoformat(), 'temp': t, 'precip_mm': r, 'snow_cm': s}
             for i, (t, r, s) in enumerate(zip(temps, rains, snows))]
    return [{'id': k, 'status': 'ok', 'hours': hours} for k in ids]


class EpandageTests(unittest.TestCase):
    def setUp(self):
        self.cfg = e.load_config()
        self.now = at(1, 10)

    def test_rain_then_night_refreeze_ready_for_745(self):
        # Pluie de 12 h à 18 h (1,5 mm/h) à +2 °C, 0,5 °C de 22 h à 2 h, puis -3 °C -> regel la nuit : prêt pour 7 h 45.
        temps = [2] * 12 + [0.5] * 4 + [-3] * 12
        rains = [0, 0] + [1.5] * 6 + [0] * 20
        out = e.plan(models(at(1, 10), temps, rains), [], 10, self.now, TZ, self.cfg)
        self.assertEqual(len(out), 1)
        it = out[0]
        self.assertEqual(it['type'], 'regel')
        self.assertEqual(it["glace"], at(2, 2).isoformat())
        self.assertEqual(it['echeance'], at(2, 7, 45).isoformat())
        self.assertEqual(it['depart'], at(2, 5, 30).isoformat())
        self.assertEqual(it['produit'], 'Sel mélangé au calcium')
        self.assertIn('9 mm', it['raison'])

    def test_lots_of_water_adds_abrasive_and_deep_cold_is_abrasive_only(self):
        self.assertIn('abrasif', e.product(-5, 15, self.cfg)[0])
        self.assertEqual(e.product(-22, 2, self.cfg)[0], 'Abrasif')
        self.assertEqual(e.product(-15, 2, self.cfg)[0], 'Sel mélangé au calcium')

    def test_melt_without_rain_needs_snow_on_ground(self):
        # 6 h à +4 °C sans pluie, puis -2 °C l'après-midi : fonte et regel de jour -> épandage au regel.
        temps = [4] * 6 + [-2] * 6
        out = e.plan(models(at(1, 10), temps, [0] * 12), [], 15, self.now, TZ, self.cfg)
        self.assertEqual(out[0]['glace'], at(1, 16).isoformat())
        self.assertEqual(out[0]['depart'], at(1, 16).isoformat())
        self.assertIsNone(out[0]['echeance'])
        self.assertEqual(e.plan(models(at(1, 10), temps, [0] * 12), [], 0, self.now, TZ, self.cfg), [])

    def test_no_refreeze_no_spreading(self):
        out = e.plan(models(at(1, 10), [3] * 24, [1] * 24), [], 10, self.now, TZ, self.cfg)
        self.assertEqual(out, [])

    def test_confirmed_freezing_rain(self):
        temps = [-2] * 24
        rains = [0] * 14 + [1] * 4 + [0] * 6  # bruine verglaçante dès 0 h le 2
        cons = [{'date': '2026-12-02', 'risques_confirmes': ['Verglas / grésil']}]
        out = e.plan(models(at(1, 10), temps, rains), cons, 10, self.now, TZ, self.cfg)
        self.assertEqual(out[0]['type'], 'verglas')
        self.assertEqual(out[0]['glace'], at(2, 0).isoformat())
        self.assertEqual(out[0]['depart'], at(2, 5, 30).isoformat())
        # Verglas seulement « à confirmer » : rien.
        cons = [{'date': '2026-12-02', 'risques_confirmes': []}]
        self.assertEqual(e.plan(models(at(1, 10), temps, rains), cons, 10, self.now, TZ, self.cfg), [])

    def test_freezing_rain_in_the_night_text_goes_to_the_next_morning(self):
        # 26 nov. 2026 : ECCC annonce « pluie verglaçante au cours de la nuit » pour jeudi; les modèles sont au sec
        # jeudi (-9 °C) et mouillés vendredi à 2 h près de 0 °C -> épandage vendredi matin, pas jeudi à 6 h.
        temps = [-9] * 14 + [-1] * 12
        rains = [0] * 16 + [0.5] * 6 + [0] * 4
        cons = [{'date': '2026-12-01', 'risques_confirmes': ['Verglas / grésil'],
                 'sources': [{'source': 'eccc', 'risk': 'Verglas / grésil'}, {'source': 'met', 'risk': 'Sans risque'},
                             {'source': 'mb', 'risk': 'Pluie / neige'}]}]
        pop = {'fenetres': [{'debut': '2026-12-02T00:00:00Z', 'fin': '2026-12-02T12:00:00Z', 'pop': 90}]}
        out = e.plan(models(at(1, 10), temps, rains), cons, 10, self.now, TZ, self.cfg, (), pop)
        self.assertEqual(out[0]['glace'], at(2, 2).isoformat())
        self.assertEqual(out[0]['echeance'], at(2, 7, 45).isoformat())
        self.assertGreaterEqual(out[0]['probabilite'], 70)
        self.assertEqual(out[0]['probabilite_detail'], {'modeles': 100, 'sites': 50, 'precipitation': 90})

    def test_announced_but_models_dry_is_not_planned(self):
        cons = [{'date': '2026-12-01', 'risques_confirmes': ['Verglas / grésil'],
                 'sources': [{'source': 'eccc', 'risk': 'Verglas / grésil'}, {'source': 'met', 'risk': 'Sans risque'},
                             {'source': 'mb', 'risk': 'Sans risque'}, {'source': 'mm', 'risk': 'Sans risque'}]}]
        pop = {'fenetres': [{'debut': '2026-12-01T12:00:00Z', 'fin': '2026-12-02T00:00:00Z', 'pop': 0}]}
        self.assertEqual(e.plan(models(at(1, 10), [-9] * 30, [0] * 30), cons, 10, self.now, TZ, self.cfg, (), pop), [])

    def test_single_model_hours_do_not_count(self):
        temps = [2] * 8 + [-3] * 8
        out = e.plan(models(at(1, 10), temps, [2] * 6 + [0] * 10, ids=('gfs',)), [], 10, self.now, TZ, self.cfg)
        self.assertEqual(out, [])


if __name__ == '__main__':
    unittest.main()
