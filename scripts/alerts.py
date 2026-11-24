"""Alertes sur les téléphones de l'équipe : notifications du site (Web Push).

Chaque alerte n'est envoyée qu'une fois (mémoire : data/alerts-state.json).

Déclencheurs choisis par Martin :
- alerte officielle d'Environnement Canada pour le secteur;
- sortie prévue par le plan, puis changement d'heure de départ d'une heure ou plus, ou annulation;
  un changement ou une annulation n'est annoncé que si deux passages de suite sont d'accord
  (le robot passe toutes les heures pendant une tempête), sauf départ dans moins de 3 h;
- probabilité de 5 cm et plus (ensemble européen) de 50 % ou plus pour aujourd'hui ou demain;
- risque de verglas, ou pluie sur la neige au sol (fonte) : prévoir l'abrasif;
  seulement si le risque est confirmé (Environnement Canada, 2 sources, ou une source mesurée
  fiable : voir trust.py et confirm_risks dans collect.py);
- poudrerie ou glace par grand vent (rafales de 50 km/h et plus avec de la neige au sol);
- d'avril à novembre : forte pluie ou orage pendant la journée de chantier (heure de début);
- période de dégel du MTQ (charges réduites) : 3 jours avant, au début et à la fin.
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


CONFIRME_MIN = 30   # deux passages « d'accord » : nouvelle heure à 30 min près
URGENT_H = 3        # départ dans moins de 3 h : pas d'attente de confirmation


def confirmed(state, key, value, now, depart=None):
    """Anti-va-et-vient : un changement n'est annoncé que si le passage précédent voyait déjà la même chose
    (pendant une tempête, le robot passe toutes les heures). Départ imminent : annoncé tout de suite."""
    if depart is not None and now is not None and dt.datetime.fromisoformat(depart) - now <= dt.timedelta(hours=URGENT_H):
        return True
    prev = state.get('candidats', {}).get(key)
    if prev is None:
        return False
    if value is None or prev is None:
        return prev == value
    return abs((dt.datetime.fromisoformat(value) - dt.datetime.fromisoformat(prev)).total_seconds()) <= CONFIRME_MIN * 60


def plans(weather, state, today, now=None, pending=None):
    """pending : candidats de ce passage (changements vus une première fois), à confirmer au suivant."""
    msgs, seen = [], {}
    pending = {} if pending is None else pending
    for p in weather.get('plan') or []:
        if p.get('statut') not in ('sortie', 'possible') or not p.get('depart'):
            continue
        day = p['depart'][:10]
        seen[day] = p['depart']
        prev = state.get('plans', {}).get(day)
        final = p.get('final') or {}
        lines = [('Passage rapide en fin de journée ' if p.get('mode') == 'soir' else 'Départ ') + f"{hhmm(p['depart'])}" + (f" · propre pour {hhmm(p['echeance'])}" if p.get('echeance') else ''),
                 f"≈ {p['total_cm']:g} cm (de {p['fourchette_cm'][0]:g} à {p['fourchette_cm'][1]:g})" + (f" · fin vers {hhmm(p['fin'])}" if p.get('fin') else '')]
        if final.get('heure'):
            lines.append({'deuxieme_tournee': '2e tournée', 'reprise_matin': 'Reprise le lendemain matin'}.get(final.get('type'), 'Nettoyage final') + f" {hhmm(final['heure'])}")
        if p.get('ensemble'):
            lines.append(f"Ensemble européen : {p['ensemble']['prob_5cm']} % de chances de 5 cm+")
        sure = [f"{r['nom'].split(' (')[0].split(' ·')[0]} {r['cm']:g} cm" for r in (p.get('fiables') or []) if r.get('statut') == 'mesurée'][:3]
        if sure:
            lines.append('Modèles les plus fiables : ' + ', '.join(sure))
        word = 'Sortie prévue' if p['statut'] == 'sortie' else 'Sortie possible'
        if prev is None:
            msgs.append({'key': f'plan:{day}:{p["depart"]}', 'title': f'{word} {day_label(p["depart"])} à {hhmm(p["depart"])}',
                         'message': '\n'.join(lines), 'priority': 4, 'tags': ['snowflake']})
        else:
            moved = abs((dt.datetime.fromisoformat(p['depart']) - dt.datetime.fromisoformat(prev)).total_seconds()) / 60
            if moved >= MOVE_MIN and confirmed(state, f'plan:{day}', p['depart'], now, p['depart']):
                msgs.append({'key': f'plan:{day}:{p["depart"]}', 'title': f'Changement : départ {day_label(p["depart"])} à {hhmm(p["depart"])}',
                             'message': f'Avant : {hhmm(prev)}.\n' + '\n'.join(lines), 'priority': 4, 'tags': ['snowflake', 'arrows_counterclockwise']})
            else:
                if moved >= MOVE_MIN:
                    pending[f'plan:{day}'] = p['depart']  # vu une première fois : à confirmer au prochain passage
                seen[day] = prev  # on garde l'heure annoncée comme référence
    for day, dep in state.get('plans', {}).items():
        if day not in seen and day >= str(today):
            if state.get('candidats', {}).get(f'annule:{day}') == dep:  # déjà absente au passage précédent
                msgs.append({'key': f'annule:{day}:{dep}', 'title': f'Sortie annulée {day_label(dep)}',
                             'message': f'Le plan ne prévoit plus 5 cm (départ annoncé : {hhmm(dep)}). Vérifier le site.', 'priority': 3, 'tags': ['white_check_mark']})
            else:
                pending[f'annule:{day}'] = dep  # plus de sortie : à confirmer au prochain passage
                seen[day] = dep  # la sortie annoncée reste la référence en attendant
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
        # Seuls les risques confirmés (source officielle, 2 sources ou source mesurée fiable) déclenchent une alerte.
        risks = d.get('risques_confirmes', d.get('risks', []))
        if 'Poudrerie' in risks or 'Glace (vent)' in risks:
            kind = 'Poudrerie probable' if 'Poudrerie' in risks else 'Grand vent : glace au sol'
            msgs.append({'key': f'vent:{d["date"]}', 'title': f'{kind} {day_label(d["date"])}',
                         'message': f'Rafales jusqu’à ≈ {d.get("rafales_kmh") or 50} km/h avec de la neige au sol : prévoir une sortie de déneigement des accumulations et de l’abrasif.',
                         'priority': 4, 'tags': ['dash']})
        if weather.get('epandage') is not None:
            continue  # le plan d'épandage (heure et produit) remplace les alertes génériques de verglas et de fonte
        if 'Verglas / grésil' in risks:
            msgs.append({'key': f'verglas:{d["date"]}', 'title': f'Risque de verglas {day_label(d["date"])}',
                         'message': 'Verglas ou grésil dans les prévisions : prévoir une sortie d’abrasif.', 'priority': 4, 'tags': ['warning']})
        elif ground >= 2 and ('Pluie' in risks or 'Pluie / neige' in risks) and (d.get('high_mean') or 0) > 1:
            msgs.append({'key': f'fonte:{d["date"]}', 'title': f'Pluie sur la neige {day_label(d["date"])}',
                         'message': f'Neige au sol (≈ {ground:g} cm) et pluie avec redoux : fonte probable, prévoir abrasif et bord de rue.', 'priority': 3, 'tags': ['droplet']})
    return msgs


def spreading(weather):
    """Plan d'épandage (scripts/epandage.py) : heure de départ, produit et raison, une alerte par sortie."""
    msgs = []
    for it in weather.get('epandage') or []:
        dep = it['depart']
        title = f"Épandage {day_label(dep[:10])} {hhmm(dep)}"
        msg = f"{it['produit']} · {it['raison']}" + (f" · prêt pour {hhmm(it['echeance'])}" if it.get('echeance') else '') +               (' · avec la tournée de déneigement' if it.get('avec_deneigement') else '')
        msgs.append({'key': f"epandage:{it['glace'][:10]}:{it['type']}", 'title': title, 'message': msg, 'priority': 4, 'tags': ['warning']})
    return msgs


def heavy_rain(weather, today):
    """Saison des chantiers : heure de début de forte pluie ou d'orage, aujourd'hui ou demain, de 6 h à 19 h."""
    msgs = []
    if not 4 <= today.month <= 11:
        return msgs
    for d in (weather.get('consensus') or [])[:2]:
        f = d.get('forte_pluie')
        if not f:
            continue
        t = dt.datetime.fromisoformat(f['heure'])
        if not 6 <= t.hour < 19:
            continue
        what = 'Orage' if f.get('orage') else 'Forte pluie'
        qty = f' (≈ {f["mm_3h"]:g} mm en 3 h)' if f.get('mm_3h') else ''
        msgs.append({'key': f'pluie:{d["date"]}', 'title': f'{what} {day_label(d["date"])} vers {hhmm(f["heure"])}',
                     'message': f'Début prévu vers {hhmm(f["heure"])}{qty} : prévoir fermer les trous et protéger le chantier.',
                     'priority': 4, 'tags': ['cloud_with_rain']})
    return msgs


def thaw(weather, today):
    """Période de dégel du MTQ (restrictions de charge) : 3 jours avant, au début et à la fin."""
    g = (weather.get('routes') or {}).get('degel') or {}
    if not g.get('debut') or not g.get('fin'):
        return []
    a, b = dt.date.fromisoformat(g['debut']), dt.date.fromisoformat(g['fin'])
    zone = g.get('zone') or 'zone de Saint-Prosper'
    if a - dt.timedelta(days=3) <= today < a:
        return [{'key': f'degel:bientot:{a}', 'title': f'Dégel : charges réduites dès le {day_label(str(a))}',
                 'message': f'Période de dégel du MTQ ({zone}) du {day_label(str(a))} au {day_label(str(b))} : charges réduites pour les camions. Planifier le transport de la machinerie.',
                 'priority': 4, 'tags': ['truck']}]
    if a <= today <= b:
        return [{'key': f'degel:debut:{a}', 'title': f'Période de dégel en cours jusqu’au {day_label(str(b))}',
                 'message': f'MTQ, {zone} : charges réduites pour les camions jusqu’au {day_label(str(b))}.', 'priority': 4, 'tags': ['truck']}]
    if b < today <= b + dt.timedelta(days=2):
        return [{'key': f'degel:fin:{b}', 'title': 'Fin de la période de dégel',
                 'message': f'MTQ, {zone} : la période de dégel s’est terminée le {day_label(str(b))}. Charges normales.', 'priority': 3, 'tags': ['truck']}]
    return []


def run(weather, state_path, today=None, pusher=None, now=None):
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
    now = now or dt.datetime.now(dt.timezone.utc)
    pending = {}
    plan_msgs, seen = plans(weather, state, today, now, pending)
    msgs = official(weather) + plan_msgs + probability(weather, today) + ice_melt(weather, today) + spreading(weather) + heavy_rain(weather, today) + thaw(weather, today)
    sent_keys = set(state.get('sent', []))
    out = []
    for m in msgs:
        if m['key'] in sent_keys:
            continue
        if pusher.broadcast(m):  # une alerte ratée sera retentée à la prochaine collecte
            out.append(m['title'])
            sent_keys.add(m['key'])
    state = {'plans': seen, 'candidats': pending, 'sent': sorted(sent_keys)[-300:], 'updated': dt.datetime.now(dt.timezone.utc).isoformat(), 'active': True}
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    pusher.save()
    return out
