"""Alertes sur les téléphones de l'équipe : notifications du site (Web Push).

Chaque alerte n'est envoyée qu'une fois (mémoire : data/alerts-state.json).

Déclencheurs choisis par Martin :
- alerte officielle d'Environnement Canada pour le secteur;
- sortie prévue par le plan, puis changement d'heure de départ d'une heure ou plus, ou annulation;
- probabilité de 5 cm et plus (ensemble européen) de 50 % ou plus pour aujourd'hui ou demain;
- risque de verglas, ou pluie sur la neige au sol (fonte) : prévoir l'abrasif;
- poudrerie ou glace par grand vent (rafales de 50 km/h et plus avec de la neige au sol).
"""
import datetime as dt
import hashlib
import json
import os
import urllib.request

SITE = 'https://mdulac86.github.io/Deneigement/'
PROB = 50
MOVE_MIN = 60


def hhmm(iso):
    t = dt.datetime.fromisoformat(iso)
    return f'{t.hour} h {t.minute:02d}'


def day_label(iso):
    t = dt.datetime.fromisoformat(iso) if 'T' in iso else dt.datetime.fromisoformat(iso + 'T12:00:00')
    days = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
    months = ['janv.', 'févr.', 'mars', 'avril', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.']
    return f'{days[t.weekday()]} {t.day} {months[t.month - 1]}'


def texts(obj, out=None):
    """Textes français d'une alerte ECCC, quelle que soit la structure exacte."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k.endswith('_fr') or k in ('headline', 'event', 'description', 'text')):
                out.append(v)
            elif isinstance(v, dict) and isinstance(v.get('fr'), str) and k in ('headline', 'event', 'description', 'text', 'alert_name', 'alert_text'):
                out.append(v['fr'])
            elif isinstance(v, (dict, list)):
                texts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            texts(v, out)
    return out


def official(weather):
    msgs = []
    for a in (weather.get('official_alerts') or {}).get('items', []):
        t = [x.strip() for x in texts(a) if x and x.strip()]
        key = 'eccc:' + str(a.get('id') or hashlib.sha1(json.dumps(a, sort_keys=True).encode()).hexdigest()[:16])
        title = (t[0] if t else 'Alerte météo')[:90]
        body = ' '.join(t[1:3])[:400] or 'Alerte officielle d’Environnement Canada pour le secteur de Saint-Prosper.'
        msgs.append({'key': key, 'title': 'Alerte officielle : ' + title, 'message': body, 'priority': 5, 'tags': ['warning']})
    return msgs


def plans(weather, state, today):
    msgs, seen = [], {}
    for p in weather.get('plan') or []:
        if p.get('statut') not in ('sortie', 'possible') or not p.get('depart'):
            continue
        day = p['depart'][:10]
        seen[day] = p['depart']
        prev = state.get('plans', {}).get(day)
        final = p.get('final') or {}
        lines = [f"Départ {hhmm(p['depart'])}" + (f" · propre pour {hhmm(p['echeance'])}" if p.get('echeance') else ''),
                 f"≈ {p['total_cm']:g} cm (de {p['fourchette_cm'][0]:g} à {p['fourchette_cm'][1]:g})" + (f" · fin vers {hhmm(p['fin'])}" if p.get('fin') else '')]
        if final.get('heure'):
            lines.append(('2e tournée' if final.get('type') == 'deuxieme_tournee' else 'Nettoyage final') + f" {hhmm(final['heure'])}")
        if p.get('ensemble'):
            lines.append(f"Ensemble européen : {p['ensemble']['prob_5cm']} % de chances de 5 cm+")
        word = 'Sortie prévue' if p['statut'] == 'sortie' else 'Sortie possible'
        if prev is None:
            msgs.append({'key': f'plan:{day}:{p["depart"]}', 'title': f'{word} {day_label(p["depart"])} à {hhmm(p["depart"])}',
                         'message': '\n'.join(lines), 'priority': 4, 'tags': ['snowflake']})
        else:
            moved = abs((dt.datetime.fromisoformat(p['depart']) - dt.datetime.fromisoformat(prev)).total_seconds()) / 60
            if moved >= MOVE_MIN:
                msgs.append({'key': f'plan:{day}:{p["depart"]}', 'title': f'Changement : départ {day_label(p["depart"])} à {hhmm(p["depart"])}',
                             'message': f'Avant : {hhmm(prev)}.\n' + '\n'.join(lines), 'priority': 4, 'tags': ['snowflake', 'arrows_counterclockwise']})
            else:
                seen[day] = prev  # petit changement : on garde l'heure annoncée comme référence
    for day, dep in state.get('plans', {}).items():
        if day not in seen and day >= str(today):
            msgs.append({'key': f'annule:{day}:{dep}', 'title': f'Sortie annulée {day_label(dep)}',
                         'message': f'Le plan ne prévoit plus 5 cm (départ annoncé : {hhmm(dep)}). Vérifier le site.', 'priority': 3, 'tags': ['white_check_mark']})
    return msgs, seen


def probability(weather, today):
    msgs = []
    for d in (weather.get('ensemble') or {}).get('jours', []):
        if d['date'] in (str(today), str(today + dt.timedelta(days=1))) and d.get('prob_5cm', 0) >= PROB:
            msgs.append({'key': f'prob:{d["date"]}', 'title': f'{d["prob_5cm"]} % de chances de 5 cm+ {day_label(d["date"])}',
                         'message': f'Ensemble européen (51 versions) : médiane {d["p50_cm"]:g} cm, de {d["p10_cm"]:g} à {d["p90_cm"]:g} cm. Surveiller le plan de sortie.',
                         'priority': 3, 'tags': ['snowflake']})
    return msgs


def snow_on_ground(weather):
    vals = [s['latest']['depth_cm'] for s in (weather.get('snow_depth') or {}).get('stations', [])
            if s.get('latest') and s['latest'].get('depth_cm') is not None]
    recs = [r for r in (weather.get('climate') or {}).get('records', []) if r.get('depth_cm') is not None]
    if recs:
        vals.append(recs[-1]['depth_cm'])
    return max(vals) if vals else 0


def ice_melt(weather, today):
    msgs, ground = [], snow_on_ground(weather)
    for d in (weather.get('consensus') or [])[:2]:
        risks = d.get('risks', [])
        if 'Poudrerie' in risks or 'Glace (vent)' in risks:
            kind = 'Poudrerie probable' if 'Poudrerie' in risks else 'Grand vent : glace au sol'
            msgs.append({'key': f'vent:{d["date"]}', 'title': f'{kind} {day_label(d["date"])}',
                         'message': f'Rafales jusqu’à ≈ {d.get("rafales_kmh") or 50} km/h avec de la neige au sol : prévoir une sortie de déneigement des accumulations et de l’abrasif.',
                         'priority': 4, 'tags': ['dash']})
        if 'Verglas / grésil' in risks:
            msgs.append({'key': f'verglas:{d["date"]}', 'title': f'Risque de verglas {day_label(d["date"])}',
                         'message': 'Verglas ou grésil dans les prévisions : prévoir une sortie d’abrasif.', 'priority': 4, 'tags': ['warning']})
        elif ground >= 2 and ('Pluie' in risks or 'Pluie / neige' in risks) and (d.get('high_mean') or 0) > 1:
            msgs.append({'key': f'fonte:{d["date"]}', 'title': f'Pluie sur la neige {day_label(d["date"])}',
                         'message': f'Neige au sol (≈ {ground:g} cm) et pluie avec redoux : fonte probable, prévoir abrasif et bord de rue.', 'priority': 3, 'tags': ['droplet']})
    return msgs


def run(weather, state_path, today=None, pusher=None):
    """Envoie les nouvelles alertes en notifications du site (Web Push).
    Sans téléphone abonné, rien n'est envoyé ni marqué comme envoyé."""
    vapid = os.environ.get('VAPID_PRIVATE_KEY')
    if pusher is None and vapid:
        import webpush_channel
        try:
            pusher = webpush_channel.Pusher(vapid, state_path.parent / 'push-subscriptions.json')
        except Exception as e:  # boîte d'inscription injoignable : on réessaiera
            print('inscriptions non lues :', e)
            pusher = None
    today = today or dt.date.today()
    try:
        state = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    if pusher:
        pusher.welcome()
    if not (pusher and pusher.subs):
        state['active'] = False
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        if pusher:
            pusher.save()
        return []
    plan_msgs, seen = plans(weather, state, today)
    msgs = official(weather) + plan_msgs + probability(weather, today) + ice_melt(weather, today)
    sent_keys = set(state.get('sent', []))
    out = []
    for m in msgs:
        if m['key'] in sent_keys:
            continue
        if pusher.broadcast(m):  # une alerte ratée sera retentée à la prochaine collecte
            out.append(m['title'])
            sent_keys.add(m['key'])
    state = {'plans': seen, 'sent': sorted(sent_keys)[-300:], 'updated': dt.datetime.now(dt.timezone.utc).isoformat(), 'active': True}
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    pusher.save()
    return out
