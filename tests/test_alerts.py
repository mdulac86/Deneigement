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

    def run_once(self, w, now=dt.datetime(2026, 12, 9, 12, tzinfo=dt.timezone.utc)):
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
        return alerts.run(w, self.path, pusher=Fake(), today=TODAY, now=now)

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
        self.assertEqual(len(self.sent), n)  # changement vu une seule fois : on attend le passage suivant
        self.run_once(weather('2026-12-10T05:00:00-05:00'))
        self.assertTrue(self.titles()[-1].startswith('Changement : départ jeudi 10 déc. à 5 h 00'))
        self.assertIn('Avant : 3 h 30', self.sent[-1]['message'])
        n = len(self.sent)
        self.run_once(weather(None))
        self.assertEqual(len(self.sent), n)  # annulation à confirmer
        self.run_once(weather(None))
        self.assertTrue(self.titles()[-1].startswith('Sortie annulée'))

    def test_back_and_forth_sends_nothing(self):
        self.run_once(weather())
        n = len(self.sent)
        for dep in ('2026-12-10T05:00:00-05:00', '2026-12-10T03:30:00-05:00', '2026-12-10T05:30:00-05:00', None, '2026-12-10T03:30:00-05:00'):
            self.run_once(weather(dep))  # le plan hésite d'une heure à l'autre
        self.assertEqual(len(self.sent), n)

    def test_imminent_change_is_sent_at_once(self):
        self.run_once(weather())
        soon = dt.datetime(2026, 12, 10, 7, 30, tzinfo=dt.timezone.utc)  # 2 h 30 heure locale
        self.run_once(weather('2026-12-10T04:30:00-05:00'), now=soon)
        self.assertTrue(self.titles()[-1].startswith('Changement : départ jeudi 10 déc. à 4 h 30'))

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

    def test_thaw_period_before_start_and_end(self):
        g = {'zone': 'Zone 1', 'debut': '2027-03-15', 'fin': '2027-05-14'}
        w = {'routes': {'degel': g}}
        self.assertEqual(alerts.thaw(w, dt.date(2027, 3, 1)), [])
        self.assertTrue(alerts.thaw(w, dt.date(2027, 3, 12))[0]['title'].startswith('Dégel : charges réduites dès le lundi 15 mars'))
        self.assertTrue(alerts.thaw(w, dt.date(2027, 3, 20))[0]['title'].startswith('Période de dégel en cours'))
        self.assertEqual(alerts.thaw(w, dt.date(2027, 5, 15))[0]['title'], 'Fin de la période de dégel')
        self.assertEqual(alerts.thaw(w, dt.date(2027, 6, 1)), [])

    def test_unconfirmed_risk_sends_no_alert(self):
        w = weather(depart=None, risks=['Verglas / grésil'])
        w['consensus'][0]['risques_confirmes'] = []  # annoncé par une seule source non mesurée
        self.run_once(w)
        self.assertNotIn('Risque de verglas jeudi 10 déc.', self.titles())
        w['consensus'][0]['risques_confirmes'] = ['Verglas / grésil']
        self.run_once(w)
        self.assertIn('Risque de verglas jeudi 10 déc.', self.titles())

    def test_spreading_plan_replaces_generic_ice_alerts(self):
        w = weather(depart=None, risks=['Verglas / grésil'])
        w['epandage'] = [{'type': 'regel', 'glace': '2026-12-10T02:00:00-05:00', 'depart': '2026-12-10T05:30:00-05:00',
                          'echeance': '2026-12-10T07:45:00-05:00', 'produit': 'Sel mélangé au calcium',
                          'raison': '≈ 9 mm de pluie, puis regel sous 0 °C', 'avec_deneigement': False}]
        self.run_once(w)
        t = self.titles()
        self.assertIn('Épandage jeudi 10 déc. 5 h 30', t)
        self.assertNotIn('Risque de verglas jeudi 10 déc.', t)
        msg = next(m['message'] for m in self.sent if m['title'].startswith('Épandage'))
        self.assertIn('Sel mélangé au calcium', msg)
        self.assertIn('prêt pour 7 h 45', msg)
        n = len(self.sent)
        w['epandage'][0]['depart'] = '2026-12-10T05:00:00-05:00'
        self.run_once(w)
        self.assertEqual(len(self.sent), n)  # même glace, heure ajustée : pas de nouvelle alerte

    def test_plan_names_the_most_reliable_models(self):
        w = weather()
        w['plan'][0]['fiables'] = [{'nom': 'ECMWF AIFS (européen, IA)', 'cm': 7.2, 'statut': 'mesurée'},
                                   {'nom': 'NBM 2,5 km · NOAA (synthèse)', 'cm': 9.0, 'statut': 'non mesurée'}]
        self.run_once(w)
        msg = next(m['message'] for m in self.sent if m['title'].startswith('Sortie prévue'))
        self.assertIn('Modèles les plus fiables : ECMWF AIFS 7.2 cm', msg)
        self.assertNotIn('NBM', msg)  # pas encore mesuré : pas cité comme fiable


if __name__ == '__main__':
    unittest.main()
