import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import alerts  # noqa: E402

TODAY = dt.date(2026, 12, 9)


def weather(depart='2026-12-10T03:30:00-05:00', items=(), prob=20, risks=('Neige',), ground=0):
    plan = [] if depart is None else [{'statut': 'sortie', 'depart': depart, 'echeance': '2026-12-10T07:45:00-05:00', 'total_cm': 8.3,
                                       'fourchette_cm': [5.1, 12.0], 'fin': '2026-12-10T08:00:00-05:00',
                                       'final': {'heure': '2026-12-10T09:00:00-05:00', 'type': 'nettoyage_final'}, 'ensemble': {'prob_5cm': 62}}]
    return {'plan': plan, 'official_alerts': {'items': list(items)},
            'ensemble': {'jours': [{'date': '2026-12-10', 'prob_5cm': prob, 'p10_cm': 1, 'p50_cm': 6, 'p90_cm': 11}]},
            'consensus': [{'date': '2026-12-10', 'risks': list(risks), 'high_mean': 3}],
            'snow_depth': {'stations': [{'latest': {'depth_cm': ground}}]}, 'climate': {'records': []}}


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / 'state.json'
        self.sent = []

    def run_once(self, w):
        test = self

        class Fake:
            subs = [{'endpoint': 'https://x'}]

            def welcome(self):
                pass

            def broadcast(self, m):
                test.sent.append({'title': m['title'], 'message': m['message'], 'priority': m['priority']})
                return True

            def save(self):
                pass
        return alerts.run(w, self.path, pusher=Fake(), today=TODAY)

    def titles(self):
        return [m['title'] for m in self.sent]

    def test_no_phone_sends_nothing_and_remembers_nothing(self):
        self.assertEqual(alerts.run(weather(), self.path, today=TODAY), [])
        self.run_once(weather())
        self.assertTrue(any(t.startswith('Sortie prévue') for t in self.titles()))

    def test_plan_sent_once_then_change_then_cancel(self):
        self.run_once(weather())
        self.assertIn('Sortie prévue jeudi 10 déc. à 3 h 30', self.titles())
        n = len(self.sent)
        self.run_once(weather())
        self.assertEqual(len(self.sent), n)  # pas de doublon
        self.run_once(weather('2026-12-10T04:00:00-05:00'))
        self.assertEqual(len(self.sent), n)  # 30 min : pas d'alerte
        self.run_once(weather('2026-12-10T05:00:00-05:00'))
        self.assertTrue(self.titles()[-1].startswith('Changement : départ jeudi 10 déc. à 5 h 00'))
        self.assertIn('Avant : 3 h 30', self.sent[-1]['message'])
        self.run_once(weather(None))
        self.assertTrue(self.titles()[-1].startswith('Sortie annulée'))

    def test_official_probability_ice_and_melt(self):
        alert = {'id': 'abc', 'alert_name_fr': 'avertissement de neige', 'alert_text_fr': '15 à 25 cm attendus.'}
        self.run_once(weather(depart=None, items=[alert], prob=70, risks=['Verglas / grésil']))
        t = self.titles()
        self.assertIn('Alerte officielle : avertissement de neige', t)
        self.assertIn('70 % de chances de 5 cm+ jeudi 10 déc.', t)
        self.assertIn('Risque de verglas jeudi 10 déc.', t)
        self.sent.clear()
        self.path.unlink()
        self.run_once(weather(depart=None, risks=['Pluie'], ground=12))
        self.assertIn('Pluie sur la neige jeudi 10 déc.', self.titles())
        self.assertEqual(self.sent[-1]['priority'], 3)


if __name__ == '__main__':
    unittest.main()
