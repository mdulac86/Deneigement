import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / f'scripts/{name}.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


trust, plan = load('trust'), load('plan')
TZ = ZoneInfo('America/Toronto')


def row(id_, err, eps, missed=0, false=0):
    return {'id': id_, 'nom': id_, 'ecart_moyen_cm': err, 'episodes': eps,
            'tempetes': {'detectees': 0, 'manquees': missed, 'fausses_alertes': false}}


# Hiver dernier tel que mesuré (scores.json du 24 novembre 2026).
SCORES = {'historique': [row('aifs', 4.2, 22, 1, 0), row('ifs', 4.9, 22, 1, 2), row('gfs', 9.8, 22, 0, 6)],
          'en_direct': [row('hrdps', None, 0), row('consensus', 1.0, 10)]}


class TrustTests(unittest.TestCase):
    def test_measured_models_ranked_and_unmeasured_get_default(self):
        w = trust.weights(SCORES, ['aifs', 'ifs', 'gfs', 'nbm'])
        self.assertEqual(w['aifs']['poids'], 1.0)
        self.assertTrue(w['aifs']['poids'] > w['ifs']['poids'] > w['nbm']['poids'] > w['gfs']['poids'])
        self.assertEqual(w['nbm']['statut'], 'non mesurée')
        self.assertEqual(w['aifs']['statut'], 'mesurée')
        self.assertNotIn('consensus', w)  # le consensus n'est pas une source
        self.assertGreaterEqual(w['gfs']['poids'], trust.FLOOR)

    def test_live_episodes_update_the_weight_automatically(self):
        before = trust.weights(SCORES, ['hrrr'])['hrrr']['poids']
        later = {**SCORES, 'en_direct': SCORES['en_direct'] + [row('hrrr', 2.0, 12)]}
        after = trust.weights(later, ['hrrr'])['hrrr']
        self.assertGreater(after['poids'], before)
        self.assertEqual((after['cet_hiver'], after['statut']), (12, 'mesurée'))
        worse = {**SCORES, 'en_direct': [row('ifs-live', 15.0, 10)]}  # alias : même modèle que « ifs »
        self.assertLess(trust.weights(worse)['ifs']['poids'], trust.weights(SCORES)['ifs']['poids'])

    def test_reliable_needs_weight_and_enough_episodes(self):
        w = trust.weights(SCORES, ['nbm'])
        self.assertTrue(trust.reliable(w, 'aifs'))
        self.assertFalse(trust.reliable(w, 'gfs'))
        self.assertFalse(trust.reliable(w, 'nbm'))
        self.assertFalse(trust.reliable(w, 'inconnue'))

    def test_weighted_consensus_follows_trusted_models(self):
        t = '2026-12-01T10:00:00Z'
        series = [{'id': 'aifs', 'hours': [{'time': t, 'snow_cm': 1.0}]},
                  {'id': 'ifs', 'hours': [{'time': t, 'snow_cm': 1.2}]},
                  {'id': 'gfs', 'hours': [{'time': t, 'snow_cm': 4.0}]},
                  {'id': 'met', 'hours': [{'time': t, 'snow_cm': 3.5}]}]
        plain = plan.hourly_consensus(series, TZ)[0]
        w = plan.hourly_consensus(series, TZ, {'aifs': 1.0, 'ifs': 0.8, 'gfs': 0.15, 'met': 0.3})[0]
        self.assertEqual(plain['snow_cm'], 2.35)
        self.assertEqual(w['snow_cm'], 1.2)
        self.assertEqual(w['n'], 4)

    def test_one_model_at_30_does_not_stretch_the_range_or_trigger(self):
        """Exemple de Martin : tout le monde prévoit 5 à 10 cm, un seul en prévoit 30."""
        start = dt.datetime(2026, 12, 9, 22, tzinfo=TZ)
        rates = {'aifs': 0.8, 'ifs': 1.0, 'nbm': 0.9, 'hrdps': 0.7, 'met': 1.2, 'hrrr': 3.75}  # cm/h sur 8 h
        series = [{'id': k, 'hours': [{'time': (start + dt.timedelta(hours=i)).isoformat(), 'snow_cm': r} for i in range(8)]}
                  for k, r in rates.items()]
        hours = plan.hourly_consensus(series, TZ, {k: 0.5 for k in rates})
        self.assertTrue(all(h['hi'] <= 1.2 for h in hours))  # 30 cm de HRRR hors de la fourchette
        self.assertEqual(plan.isolated({k: r * 8 for k, r in rates.items()}), {'hrrr': 30.0})
        cfg = plan.load_config()
        p = plan.build_plan(hours, cfg, dt.datetime(2026, 12, 9, 12, tzinfo=TZ))[0]
        self.assertLessEqual(p['fourchette_cm'][1], 10)
        self.assertEqual(p['isoles'], {'hrrr': 30.0})
        self.assertTrue(any('HRRR prévoit ≈ 30 cm' in x for x in p['notes']))

    def test_two_models_agreeing_high_are_not_isolated(self):
        self.assertEqual(plan.isolated({'a': 6, 'b': 7, 'c': 8, 'd': 25, 'e': 27}), {})  # deux modèles d'accord : signal réel
        self.assertEqual(plan.isolated({'a': 0.5, 'b': 1, 'c': 1.5, 'd': 6}), {})  # écart < 8 cm : pas isolé


if __name__ == '__main__':
    unittest.main()
