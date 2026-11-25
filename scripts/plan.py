"""Plan de sortie : à partir de la neige prévue heure par heure (médiane des modèles).

Règles de l'équipe (config/plan.json) :
- seuil de sortie : 2 cm de nouvelle neige prévue (config/plan.json, calibré sur le journal 2025-2026);
- 4 h par machine jusqu'à 10 cm, +1,5 h par tranche de 10 cm de plus;
- semaine et fin de semaine : commercial propre pour 7 h 45, résidentiel/locatif en acte
  de présence; nettoyage final à 9 h 00 ou à la fin de la tempête;
- neige de jour : moins de 10 cm, nettoyage le lendemain matin; 10 cm et plus en fin de journée,
  passage rapide à 16 h 30 puis reprise le lendemain matin.

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


FOURCHETTE = (0.2, 0.8)  # fourchette pondérée : un modèle isolé ne l'étire pas à lui seul
ISOLE_FACTEUR, ISOLE_CM = 2.0, 8.0  # modèle isolé : plus du double de la médiane des autres ET 8 cm de plus


def weighted_quantile(pairs, q):
    """pairs : [(valeur, poids)] -> quantile pondéré (q = 0,5 : médiane pondérée)."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    target, cum = sum(w for _, w in pairs) * q, 0.0
    for v, w in pairs:
        cum += w
        if cum >= target - 1e-9:
            return v
    return pairs[-1][0]


def weighted_median(pairs):
    return weighted_quantile(pairs, 0.5)


def isolated(totals):
    """totals : {modèle: cm sur l'épisode} -> modèles très au-dessus des autres (fausse alerte probable)."""
    out = {}
    for k, v in totals.items():
        others = [x for j, x in totals.items() if j != k]
        if len(others) < 2:
            continue
        med = statistics.median(others)
        alone = not any(x >= 0.7 * v for x in others)  # aucun autre modèle ne le rejoint
        if alone and v >= ISOLE_FACTEUR * med and v - med >= ISOLE_CM:
            out[k] = round(v, 1)
    return out


def hourly_consensus(series, tz, weights=None):
    """series : [{'id', 'hours': [{'time': ISO, 'snow_cm': float|None}]}] -> heures locales.

    Chaque heure couvre [time, time + 1 h). Une valeur absente n'est pas un zéro.
    weights : {id: poids} tiré du tableau de fiabilité (trust.py). Sans poids, médiane simple.
    Fourchette : 15 % – 85 % pondérés dès 3 modèles (un modèle isolé ne l'étire pas), min – max sinon.
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
        vals = by_hour[t]
        w = {k: (weights or {}).get(k, 1.0) for k in vals}
        pairs = [(v, w[k]) for k, v in vals.items()]
        med = weighted_median(pairs) if weights else statistics.median(vals.values())
        if len(vals) >= 3:
            lo, hi = (weighted_quantile(pairs, q) for q in FOURCHETTE)
        else:
            lo, hi = min(vals.values()), max(vals.values())
        out.append({'time': t, 'snow_cm': round(med, 2), 'lo': min(lo, med), 'hi': max(hi, med),
                    'n': len(vals), 'models': vals})
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


def plan_event(ev, cfg, now, carry=0.0):
    """carry : neige déjà au sol depuis le dernier nettoyage (petites chutes qui s'additionnent)."""
    seuil = cfg['seuil_cm']
    need = max(0.1, seuil - carry)  # ce qu'il reste à tomber pour atteindre 5 cm au sol
    totals = {}
    for h in ev:
        for k, v in (h.get('models') or {}).items():
            totals[k] = totals.get(k, 0) + v
    iso_models = isolated(totals)
    if iso_models:  # le modèle isolé ne compte pas dans le haut de la fourchette (ni dans « sortie possible »)
        ev = [{**h, 'hi': max(h['snow_cm'], min(h['hi'], max([v for k, v in h['models'].items() if k not in iso_models] or [h['hi']])))}
              if h.get('models') else h for h in ev]
    total, lo, hi = (round(sum(h[k] for h in ev), 1) for k in ('snow_cm', 'lo', 'hi'))
    start, end = ev[0]['time'], last_snow(ev, cfg) or ev[-1]['time'] + HOUR
    t5, t5_early, t5_late = reach(ev, need), reach(ev, need, 'hi'), reach(ev, need, 'lo')
    level, n = confidence(ev, total, lo, hi, now)
    base = {'debut': iso(start), 'fin': iso(end), 'total_cm': total, 'fourchette_cm': [lo, hi],
            'seuil_atteint': iso(t5), 'seuil_fourchette': [iso(t5_early), iso(t5_late)],
            'confiance': level, 'modeles': n, 'notes': [], 'deja_au_sol_cm': round(carry, 1) if carry >= 0.5 else 0,
            'isoles': iso_models}
    for k, v in iso_models.items():
        base['notes'].append(f'{k.upper()} prévoit ≈ {v:g} cm, très au-dessus des autres modèles : mis de côté (ni fourchette, ni alerte).')
    if carry >= 0.5:
        base['notes'].append(f'≈ {carry:g} cm déjà accumulés depuis le dernier nettoyage : il suffit de {need:g} cm de plus pour atteindre {seuil} cm.')
    if t5 is None:
        # « Possible » seulement si au moins 2 modèles atteignent le seuil, ou si la médiane en atteint la moitié :
        # un seul modèle à 5 cm quand les autres sont à 0 ne déclenche rien (il est nommé dans une note).
        over = sorted(k for k, v in totals.items() if v >= need and k not in iso_models)
        if t5_early is not None and len(over) < 2 and total < need / 2:
            if over:
                base['notes'].append(f'Seul {over[0].upper()} prévoit ≈ {round(totals[over[0]], 1):g} cm; les autres modèles restent loin sous {seuil} cm.')
            t5_early = None
        if t5_early is None:
            au_sol = round(carry + total, 1)
            return {**base, 'statut': 'sous_seuil', 'au_sol_apres_cm': au_sol,
                    'resume': f'Environ {total:g} cm prévus' + (f', ≈ {au_sol:g} cm accumulés au total' if carry >= 0.5 else '') + f' : sous le seuil de {seuil} cm.'}
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
        snow_dl = cum_at(ev, deadline) + carry
        dur = duration_h(snow_dl, cfg)
        ideal = floor30(deadline - dt.timedelta(hours=dur))
        dep = max(ideal, ceil30(t5))
        finish = dep + dt.timedelta(hours=dur)
        mode = 'matin'
        if finish > deadline:
            base['notes'].append(f'Le seuil arrive tard : la tournée finirait vers {fr_time(finish)}, après l’échéance de {fr_time(deadline)}.')
    else:
        # Neige de jour (règle de l'équipe) : moins de 10 cm au sol en fin de journée -> nettoyage le lendemain
        # matin; 10 cm et plus -> passage rapide en fin de journée, puis reprise le lendemain matin.
        J = cfg.get('jour') or {'seuil_soir_cm': 10, 'soir': '16:30'}
        evening = dt.datetime.combine(t5.date(), hm(J['soir']), t5.tzinfo)
        snow_eve = round(cum_at(ev, evening) + carry, 1)
        day = t5.date() + dt.timedelta(days=1)
        rules = day_rules(day, cfg)
        deadline = dt.datetime.combine(day, rules['echeance_t'], t5.tzinfo)
        if snow_eve >= J['seuil_soir_cm'] and t5 <= evening:
            mode = 'soir'
            dep = evening
            dur = duration_h(snow_eve, cfg)
            finish = dep + dt.timedelta(hours=dur)
            after = round(cum_at(ev, deadline) - cum_at(ev, evening), 1)
            mdur = duration_h(after, cfg)
            base['notes'].append(f'≈ {snow_eve:g} cm au sol en fin de journée : passage rapide à {fr_time(dep)}, puis reprise le lendemain matin.')
            if rules.get('note'):
                base['notes'].append(rules['note'])
            return {**base, 'mode': mode, 'echeance': None, 'depart': iso(dep), 'duree_h': dur,
                    'fin_tournee': iso(finish), 'neige_a_echeance_cm': None,
                    'final': {'heure': iso(floor30(deadline - dt.timedelta(hours=mdur))), 'type': 'reprise_matin',
                              'neige_cm': after, 'duree_h': mdur, 'echeance': iso(deadline)},
                    'fin_de_semaine': weekend(t5.date())}
        mode = 'matin'
        snow_dl = cum_at(ev, deadline) + carry
        dur = duration_h(snow_dl, cfg)
        dep = floor30(deadline - dt.timedelta(hours=dur))
        finish = dep + dt.timedelta(hours=dur)
        base['notes'].append(f'Moins de {J["seuil_soir_cm"]:g} cm pendant la journée : nettoyage le lendemain matin.')
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
            'fin_tournee': iso(finish), 'neige_a_echeance_cm': round(cum_at(ev, deadline) + carry, 1) if deadline else None,
            'final': final, 'fin_de_semaine': weekend(day)}


def build_plan(hours, cfg, now, carry=0.0, melt_days=()):
    """carry : neige accumulée depuis le dernier nettoyage. Elle s'ajoute d'un épisode à l'autre
    (3 jours de 2 cm finissent par faire 5 cm au sol) jusqu'à une sortie ou un jour de fonte."""
    for k in ('semaine', 'fin_de_semaine'):
        cfg[k]['echeance_t'] = hm(cfg[k]['echeance'])
    # Le plan de sortie se limite aux 108 prochaines heures (au-delà : tendance seulement).
    upcoming = [h for h in hours if h['time'] + HOUR > now and h['time'] < now + dt.timedelta(hours=108)]
    melt = set(str(d) for d in melt_days)
    plans, prev_end = [], now
    for ev in events(upcoming, cfg):
        days_between = {str(prev_end.date() + dt.timedelta(days=i)) for i in range((ev[0]['time'].date() - prev_end.date()).days + 1)}
        if carry and days_between & melt and ev[0]['time'].date() > prev_end.date():
            carry = 0.0  # redoux entre les deux épisodes : la petite neige a fondu ou s'est tassée
        p = plan_event(ev, cfg, now, carry)
        plans.append(p)
        carry = p['au_sol_apres_cm'] if p['statut'] == 'sous_seuil' else 0.0
        prev_end = ev[-1]['time'] + HOUR
    for k in ('semaine', 'fin_de_semaine'):
        cfg[k].pop('echeance_t', None)
    return [p for p in plans if p['statut'] != 'sous_seuil' or p['fourchette_cm'][1] >= 2 or p.get('au_sol_apres_cm', 0) >= 2]


def probability(p, hours, weights, ens_days=(), nbm_tranches=(), cfg=None):
    """Probabilité (%) qu'il tombe assez de neige pour une sortie sur cet épisode, moyenne de ce qui est disponible :
    - part des modèles (pondérée par leur fiabilité) dont le total de l'épisode atteint le seuil;
    - ensemble ECMWF : part des 51 versions à 2 cm et plus (5 cm si le seuil est plus haut), jour de l'épisode;
    - NBM (NOAA) : probabilité de 2,5 cm et plus en 6 h, tranches qui touchent l'épisode.
    Le modèle isolé compte pour son poids : une seule voix, pas une sortie."""
    cfg = cfg or {}
    a, b = dt.datetime.fromisoformat(p['debut']), dt.datetime.fromisoformat(p['fin'])
    need = max(0.1, cfg.get('seuil_cm', 2) - (p.get('deja_au_sol_cm') or 0))
    tot = {}
    for h in hours:
        if a <= h['time'] < b:
            for k, v in (h.get('models') or {}).items():
                tot[k] = tot.get(k, 0) + v
    parts = {}
    w = {k: (weights.get(k) or 0.45) for k in tot}
    if tot and sum(w.values()):
        parts['modeles'] = 100 * sum(w[k] for k, v in tot.items() if v >= need) / sum(w.values())
    key = 'prob_2cm' if need <= 3.5 else 'prob_5cm'
    days = {str((a + dt.timedelta(hours=i)).date()) for i in range(int((b - a).total_seconds() // 3600) + 1)}
    ens = [d.get(key) for d in ens_days if d.get('date') in days and d.get(key) is not None]
    if ens:
        parts['ensemble'] = max(ens)
    nb = [t['p_2_5cm'] for t in nbm_tranches if t.get('p_2_5cm') is not None
          and dt.datetime.fromisoformat(t['debut'].replace('Z', '+00:00')) < b and dt.datetime.fromisoformat(t['fin'].replace('Z', '+00:00')) > a]
    if nb:
        parts['nbm'] = max(nb)
    if not parts:
        return None, {}
    return round(sum(parts.values()) / len(parts)), {k: round(v) for k, v in parts.items()}


def apply_probability(plans, cfg):
    """Une sortie « possible » sous la probabilité minimale (config possible_min_pct) redevient « sous le seuil »."""
    lim = cfg.get('possible_min_pct', 30)
    for p in plans:
        if p.get('statut') == 'possible' and p.get('probabilite') is not None and p['probabilite'] < lim:
            p['statut'] = 'sous_seuil'
            p['au_sol_apres_cm'] = round((p.get('deja_au_sol_cm') or 0) + p['total_cm'], 1)
            p['notes'] = [x for x in p['notes'] if 'n’est atteint que par' not in x and 'Le seuil arrive tard' not in x]
            p['notes'].append(f"Probabilité de sortie {p['probabilite']} % (sous {lim} %) : pas de sortie annoncée.")
            p['resume'] = f"Environ {p['total_cm']:g} cm prévus, probabilité de sortie {p['probabilite']} % : sous le seuil de {cfg['seuil_cm']} cm."
    return plans


def carry_from_records(records, cfg):
    """Neige au sol depuis le dernier nettoyage, d'après les relevés quotidiens publiés : on additionne
    les chutes; remise à zéro après une sortie (5 cm atteints), un redoux (max ≥ 4 °C) ou de la pluie."""
    acc = 0.0
    for r in sorted(records, key=lambda r: r['date']):
        s, rain, tx = r.get('snow_cm'), r.get('rain_mm') or 0, r.get('tmax')
        if s is None:
            continue
        if rain >= 2 and s < 0.2 or (tx is not None and tx >= 4 and s < 0.2):
            acc = 0.0
            continue
        acc += s if s >= 0.2 else 0
        if acc >= cfg['seuil_cm']:
            acc = 0.0
    return round(acc, 1)
