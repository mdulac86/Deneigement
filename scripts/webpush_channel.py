"""Notifications du site (Web Push) : directement sur les téléphones, sans application à installer.

- iPhone : le site doit être ajouté à l'écran d'accueil (iOS 16.4 et plus), puis « Activer les
  notifications » dans l'onglet Sources. Android : directement dans Chrome.
- Le téléphone envoie son abonnement dans une boîte d'inscription (canal ntfy servant uniquement
  de boîte aux lettres, invisible pour l'équipe). Le robot récupère les inscriptions à chaque
  collecte et les garde dans data/push-subscriptions.json.
- Un abonnement seul ne permet pas d'envoyer de notification : il faut aussi la clé privée VAPID,
  gardée dans les secrets GitHub (VAPID_PRIVATE_KEY).
"""
import datetime as dt
import json
import urllib.request

REG_URL = 'https://ntfy.sh/dulac-deneigement-inscriptions-k7p2'
SUBJECT = 'mailto:info@dulacetfils.com'
SITE = 'https://mdulac86.github.io/Deneigement/'


def valid(sub):
    return (isinstance(sub, dict) and str(sub.get('endpoint', '')).startswith('https://')
            and isinstance(sub.get('keys'), dict) and sub['keys'].get('p256dh') and sub['keys'].get('auth'))


def poll_registrations(get=None):
    """Messages d'inscription des 13 dernières heures (ntfy garde 12 h; le robot passe aux 6 h)."""
    if get is None:
        def get(url):
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode()
    out = []
    for line in get(REG_URL + '/json?poll=1&since=13h').splitlines():
        try:
            m = json.loads(line)
            body = json.loads(m.get('message', ''))
        except ValueError:
            continue
        if isinstance(body, dict):
            out.append(body)
    return out


class Pusher:
    def __init__(self, private_key, path, get=None, send=None):
        self.key, self.path, self.send = private_key, path, send or self._webpush
        try:
            self.subs = json.loads(path.read_text(encoding='utf-8')).get('subs', [])
        except (OSError, ValueError):
            self.subs = []
        self.new = []
        known = {s['endpoint'] for s in self.subs}
        for r in poll_registrations(get):
            sub = r.get('subscription')
            if r.get('action') == 'remove' and valid(sub):
                self.subs = [s for s in self.subs if s['endpoint'] != sub['endpoint']]
                known.discard(sub['endpoint'])
            elif r.get('action') == 'add' and valid(sub) and sub['endpoint'] not in known:
                entry = {'endpoint': sub['endpoint'], 'keys': {'p256dh': sub['keys']['p256dh'], 'auth': sub['keys']['auth']},
                         'label': str(r.get('label', ''))[:40], 'added': dt.datetime.now(dt.timezone.utc).isoformat()}
                self.subs.append(entry)
                self.new.append(entry)
                known.add(sub['endpoint'])

    def _webpush(self, sub, payload):
        from pywebpush import webpush, WebPushException
        try:
            webpush(subscription_info={'endpoint': sub['endpoint'], 'keys': sub['keys']}, data=payload,
                    vapid_private_key=self.key, vapid_claims={'sub': SUBJECT}, ttl=6 * 3600, timeout=20)
            return 'ok'
        except WebPushException as e:
            code = getattr(e.response, 'status_code', None)
            return 'gone' if code in (404, 410) else f'erreur {code}'

    def payload(self, msg):
        return json.dumps({'title': msg['title'], 'body': msg['message'], 'url': SITE, 'tag': msg['key'],
                           'urgent': msg['priority'] >= 4}, ensure_ascii=False)

    def deliver(self, subs, msg):
        ok, gone = False, []
        for s in subs:
            r = self.send(s, self.payload(msg))
            if r == 'ok':
                ok = True
            elif r == 'gone':
                gone.append(s['endpoint'])  # téléphone désabonné ou site retiré de l'écran d'accueil
            else:
                print('notification non envoyée :', r)
        self.subs = [s for s in self.subs if s['endpoint'] not in gone]
        return ok

    def broadcast(self, msg):
        return self.deliver(list(self.subs), msg)

    def welcome(self):
        msg = {'key': 'bienvenue-push', 'title': 'Notifications activées',
               'message': 'Ce téléphone recevra les sorties prévues, les alertes officielles, les risques de verglas et de fonte.',
               'priority': 3}
        if self.new:
            self.deliver(self.new, msg)

    def save(self):
        self.path.write_text(json.dumps({'subs': self.subs}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
