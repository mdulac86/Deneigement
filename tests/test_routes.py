import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('routes', Path(__file__).parents[1] / 'scripts/routes.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

LAT, LON = 46.214, -70.486


def feature(lon, lat, **props):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]}, 'properties': props}


def segment(coords, etat, visi='Bonne', lames='N'):
    return {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {'NomRoute': 'route 204', 'LocalisationDebutFR': 'A', 'LocalisationFinFR': 'B',
                           'DescriptionEtatChausseeFR': etat, 'DescriptionVisibiliteFR': visi,
                           'IndicateurPresenceLamesNeige': lames, 'EnVigueurDepuis': '2026/12/01 05:00:00'}}


class RoutesTests(unittest.TestCase):
    def test_gravite_from_wording(self):
        self.assertEqual(r.gravite('Dégagée et sèche', 'Bonne', False), 0)
        self.assertEqual(r.gravite('Dégagée et mouillée', 'Bonne', False), 1)
        self.assertEqual(r.gravite('Partiellement enneigée', 'Bonne', False), 1)
        self.assertEqual(r.gravite('Enneigée', 'Bonne', False), 2)
        self.assertEqual(r.gravite('Partiellement glacée', 'Bonne', False), 2)
        self.assertEqual(r.gravite('Glacée', 'Bonne', False), 3)
        self.assertEqual(r.gravite('Dégagée et sèche', 'Réduite', False), 2)
        self.assertEqual(r.gravite('Dégagée et sèche', 'Bonne', True), 2)

    def test_collect_sorts_by_distance_and_filters_radius(self):
        layers = {
            'conditions_routieres': [segment([[-70.47, 46.21], [-70.40, 46.20]], 'Enneigée', lames='O'),
                                     segment([[-70.65, 46.15], [-70.70, 46.10]], 'Dégagée et sèche')],
            'evenements': [feature(-70.66, 46.12, numeroRoute='73', entrave='Fermeture', localisation='A-73')],
            'infos_cameras': [feature(-70.66, 46.12, IDEcamera='3563', DescriptionLocalisationFr='Aut. 73'),
                              feature(-72.5, 46.8, IDEcamera='9999', DescriptionLocalisationFr='Trop loin'),
                              feature(-70.5, 46.2, IDEcamera='abc', DescriptionLocalisationFr='Identifiant invalide')],
        }
        get = lambda url: {'features': layers[next(k for k in layers if 'ms%3A' + k in url)]}
        out = r.collect(get, LAT, LON, '2026-12-01T10:00:00Z')
        self.assertEqual(out['status'], 'ok')
        self.assertLess(out['segments'][0]['km'], out['segments'][1]['km'])
        self.assertTrue(out['segments'][0]['lames_neige'])
        self.assertEqual(out['resume']['gravite'], 2)
        self.assertEqual([c['id'] for c in out['cameras']], ['3563'])
        self.assertIn('camera.ashx?id=3563', out['cameras'][0]['video'])
        self.assertEqual(out['evenements'][0]['entrave'], 'Fermeture')

    def test_failure_keeps_previous_lists(self):
        def boom(url):
            raise OSError('hors ligne')
        prev = {'segments': [{'km': 1, 'gravite': 0, 'chaussee': 'Dégagée', 'route': 'route 204'}], 'cameras': [], 'evenements': []}
        out = r.collect(boom, LAT, LON, 'now', prev)
        self.assertEqual(out['status'], 'unavailable')
        self.assertEqual(out['segments'], prev['segments'])


if __name__ == '__main__':
    unittest.main()
