import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import alerts  # noqa: E402
import webpush_channel as wp  # noqa: E402
from test_alerts import weather, TODAY  # noqa: E402

SUB = {'endpoint': 'https://web.push.apple.com/abc', 'keys': {'p256dh': 'BP', 'auth': 'au'}}
SUB2 = {'endpoint': 'https://fcm.googleapis.com/x', 'keys': {'p256dh': 'BQ', 'auth': 'av'}}


def feed(*bodies):
    return lambda url: '\n'.join(json.dumps({'event': 'message', 'message': json.dumps(b)}) for b in bodies)


class WebPushTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.sent = []

    def pusher(self, *bodies, results=None):
        def send(sub, payload):
            self.sent.append((sub['endpoint'], json.loads(payload)))
            return (results or {}).get(sub['endpoint'], 'ok')
        return wp.Pusher('k', self.dir / 'push-subscriptions.json', get=feed(*bodies), send=send)

    def test_registration_validation_and_dedupe(self):
        p = self.pusher({'action': 'add', 'subscription': SUB, 'label': 'Martin'}, {'action': 'add', 'subscription': SUB},
                        {'action': 'add', 'subscription': {'endpoint': 'http://evil'}}, 'pas un dict')
        self.assertEqual(len(p.subs), 1)
        self.assertEqual(p.subs[0]['label'], 'Martin')
        p.welcome()
        self.assertEqual(self.sent[0][1]['title'], 'Notifications activées')
        p.save()
        p2 = self.pusher({'action': 'add', 'subscription': SUB})
        self.assertEqual((len(p2.subs), p2.new), (1, []))

    def test_alerts_go_to_all_phones_and_gone_are_removed(self):
        p = self.pusher({'action': 'add', 'subscription': SUB}, {'action': 'add', 'subscription': SUB2},
                        results={SUB2['endpoint']: 'gone'})
        out = alerts.run(weather(), self.dir / 'state.json', topic='', pusher=p, today=TODAY)
        self.assertTrue(any(t.startswith('Sortie prévue') for t in out))
        self.assertEqual([s['endpoint'] for s in json.loads((self.dir / 'push-subscriptions.json').read_text())['subs']], [SUB['endpoint']])
        payload = [m for e, m in self.sent if m['title'].startswith('Sortie prévue')][0]
        self.assertTrue(payload['urgent'])
        self.assertIn('Départ 3 h 30', payload['body'])

    def test_remove_action(self):
        p = self.pusher({'action': 'add', 'subscription': SUB})
        p.save()
        p2 = self.pusher({'action': 'remove', 'subscription': SUB})
        self.assertEqual(p2.subs, [])


if __name__ == '__main__':
    unittest.main()
