"""Plan de sortie : à partir de la neige prévue heure par heure (médiane des modèles).

Règles de l'équipe (config/plan.json) :
- seuil de sortie : 5 cm de nouvelle neige;
- 4 h par machine jusqu'à 10 cm, +1,5 h par tranche de 10 cm de plus;
- semaine et fin de semaine : commercial propre pour 7 h 45, résidentiel/locatif en acte
  de présence; nettoyage final à 9 h 00 ou à la fin de la tempête.

Fonctions pures, sans réseau, testées dans tests/test_plan.py.
"""
import datetime as dt
import json
import math
from pathlib import Path
import statistics

CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'plan.json'
HOUR = dt.timedelta(hours=1)


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def hm(text):
    h, m = text.split(':')
    return dt.time(int(h), int(m))


def floor30(t):
    return t.replace(minute=0 if t.minute < 30 else 30, second=0, microsecond=0)


def ceil30(t):
    f = floor30(t)
    return f if f == t else f + dt.timedelta(minutes=30)


def duration_h(cm, cfg):
    d = cfg['duree']
    if cm is None or cm <= d['base_max_cm']:
        return d['base_h']
    return d['base_h'] + d['par_10cm_h'] * math.ceil((cm - d['base_max_cm']) / 10 - 1e-9)


def weekend(day):
    return day.weekday() >= 5


def day_rules(day, cfg):
    return cfg['fin_de_semaine'] if weekend(day) else cfg['semaine']


def hourly_consensus(series, tz):
    """series : [{'id', 'hours': [{'time': ISO, 'snow_cm': float|None}]}] -> heures locales.

    Chaque heure couvre [time, time + 1 h). Une valeur absente n'est pas un zéro.
    """
    by_hour = {}
    for s in series:
        for h in s.get('hours', []):
            if h.get('snow_cm') is None:
                continue
            t = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(tz)
            by_hour.setdefault(t, {})[s['id']] = h['snow_cm']
    out = []
    for t in sorted(by_hour):
        vals = list(by_hour[t].values())
        out.append({'time': t, 'snow_cm': round(statistics.median(vals), 2), 'lo': min(vals), 'hi': max(vals),
                    'n': len(vals), 'models': by_hour[t]})
    return out


def events(hours, cfg):
    """Regroupe les heures de neige; une pause de 3 h ou moins ne coupe pas l'épisode."""
    groups, cur = [], []
    for h in hours:
        snowy = max(h['snow_cm'], h.get('hi', 0)) >= cfg['neige_min_cm_h']
        if snowy:
            if cur and (h['time'] - cur[-1]['time']) > HOUR * (cfg['pause_max_h'] + 1):
                groups.append(cur)
                cur = []
            cur.append(h)
    if cur:
        groups.append(cur)
    # Ajoute les heures sèches internes pour un cumul continu.
    result = []
    for g in groups:
        start, end = g[0]['time'], g[-1]['time']
        result.append([h for h in hours if start <= h['time'] <= end])
    return result


def cum_at(ev, t, key='snow_cm'):
    total = 0.0
    for h in ev:
        a, b = h['time'], h['time'] + HOUR
        if b <= t:
            total += h[key]
        elif a < t:
            total += h[key] * (t - a) / HOUR
    return total


def reach(ev, target, key='snow_cm'):
    total = 0.0
    for h in ev:
        if h[key] > 0 and total + h[key] >= target:
            return h['time'] + HOUR * ((target - total) / h[key])
        total += h[key]
    return None


def last_snow(ev, cfg, key='snow_cm'):
    snowy = [h for h in ev if h[key] >= cfg['neige_min_cm_h']]
    return snowy[-1]['time'] + HOUR if snowy else None


def confidence(ev, total, lo, hi, now):
    n = min(h['n'] for h in ev if h['snow_cm'] > 0) if any(h['snow_cm'] > 0 for h in ev) else 0
    spread = (hi - lo) / max(total, 1)
    level = 2 if n >= 3 and spread <= .6 else 1 if n >= 2 else 0
    if (ev[0]['time'] - now) > dt.timedelta(hours=48):
        level = max(0, level - 1)
    return ['Faible', 'Moyenne', 'Élevée'][level], n


def iso(t):
    return (t + dt.timedelta(seconds=30)).replace(second=0, microsecond=0).isoformat() if t else None


def fr_time(t):
    return f'{t.hour} h {t.minute:02d}'


def plan_event(ev, cfg, now):
    seuil = cfg['seuil_cm']
    total, lo, hi = (round(sum(h[k] for h in ev), 1) for k in ('snow_cm', 'lo', 'hi'))
    start, end = ev[0]['time'], last_snow(ev, cfg) or ev[-1]['time'] + HOUR
    t5, t5_early, t5_late = reach(ev, seuil), reach(ev, seuil, 'hi'), reach(ev, seuil, 'lo')
    level, n = confidence(ev, total, lo, hi, now)
    base = {'debut': iso(start), 'fin': iso(end), 'total_cm': total, 'fourchette_cm': [lo, hi],
            'seuil_atteint': iso(t5), 'seuil_fourchette': [iso(t5_early), iso(t5_late)],
            'confiance': level, 'modeles': n, 'notes': []}
    if t5 is None:
        if t5_early is None:
            return {**base, 'statut': 'sous_seuil', 'resume': f'Environ {total:g} cm prévus : sous le seuil de {seuil} cm.'}
        base['statut'] = 'possible'
        base['notes'].append(f'Le seuil de {seuil} cm n’est atteint que par le modèle le plus enneigé.')
        t5 = t5_early
    else:
        base['statut'] = 'sortie'

    # Nuit : le seuil tombe entre le début de soirée et l'échéance du matin.
    day = t5.date() if t5.time() <= day_rules(t5.date(), cfg)['echeance_t'] else t5.date() + dt.timedelta(days=1)
    rules = day_rules(day, cfg)
    deadline = dt.datetime.combine(day, rules['echeance_t'], t5.tzinfo)
    night_start = dt.datetime.combine(day - dt.timedelta(days=1), hm(cfg['debut_nuit']), t5.tzinfo)
    if night_start <= t5 <= deadline:
        snow_dl = cum_at(ev, deadline)
        dur = duration_h(snow_dl, cfg)
        ideal = floor30(deadline - dt.timedelta(hours=dur))
        dep = max(ideal, ceil30(t5))
        finish = dep + dt.timedelta(hours=dur)
        mode = 'matin'
        if finish > deadline:
            base['notes'].append(f'Le seuil arrive tard : la tournée finirait vers {fr_time(finish)}, après l’échéance de {fr_time(deadline)}.')
    else:
        deadline = None
        dep = ceil30(t5)
        dur = duration_h(min(cum_at(ev, dep + dt.timedelta(hours=4)), total), cfg)
        finish = dep + dt.timedelta(hours=dur)
        rules = day_rules(dep.date(), cfg)
        mode = 'jour'
    residual = round(total - cum_at(ev, dep), 1)
    final = None
    if residual >= cfg['final_min_cm'] and end > dep + dt.timedelta(minutes=30):
        after = max(end, finish)
        cands = [dt.datetime.combine(finish.date(), hm(c), t5.tzinfo) for c in rules['nettoyage_final']] if mode == 'matin' else []
        when = next((c for c in cands if c >= after), ceil30(after))
        kind = 'deuxieme_tournee' if residual >= seuil else 'nettoyage_final'
        final = {'heure': iso(when), 'type': kind, 'neige_cm': residual,
                 'duree_h': duration_h(residual, cfg) if kind == 'deuxieme_tournee' else None}
    if rules.get('note'):
        base['notes'].append(rules['note'])
    return {**base, 'mode': mode, 'echeance': iso(deadline), 'depart': iso(dep), 'duree_h': dur,
            'fin_tournee': iso(finish), 'neige_a_echeance_cm': round(cum_at(ev, deadline), 1) if deadline else None,
            'final': final, 'fin_de_semaine': weekend(day if mode == 'matin' else dep.date())}


def build_plan(hours, cfg, now):
    for k in ('semaine', 'fin_de_semaine'):
        cfg[k]['echeance_t'] = hm(cfg[k]['echeance'])
    # Le plan de sortie se limite aux 108 prochaines heures (au-delà : tendance seulement).
    upcoming = [h for h in hours if h['time'] + HOUR > now and h['time'] < now + dt.timedelta(hours=108)]
    plans = [plan_event(ev, cfg, now) for ev in events(upcoming, cfg)]
    for k in ('semaine', 'fin_de_semaine'):
        cfg[k].pop('echeance_t', None)
    return [p for p in plans if p['statut'] != 'sous_seuil' or p['fourchette_cm'][1] >= 2]
