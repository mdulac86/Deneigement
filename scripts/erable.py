"""Saison des sucres : date de la première coulée estimée automatiquement, chaque automne.

Règle (config/erable.json) : bonne journée de coulée = nuit à -2 °C ou moins (la nuit d'avant ou
celle du jour) puis maximum entre 3 et 10 °C. Première coulée de la saison = premier jour, à partir
du 1er février, qui ouvre 7 jours contenant au moins 3 bonnes journées.

On l'applique aux 10 derniers printemps mesurés à Saint-Prosper (station 7027660) :
- Environnement Canada (API climate-daily) pour les années anciennes;
- Climat Québec pour les plus récentes (l'API d'ECCC n'a pas encore les deux derniers printemps).
Estimation = médiane des 10 premières coulées; plus tôt / plus tard = extrêmes. Une estimation
manuelle (ex. hiver El Niño) peut la remplacer pour une saison : premiere_coulee.manuelle.
Recalculée une fois par saison, à partir de septembre. Fonctions pures sauf get_month.
"""
import datetime as dt
import json
import statistics
import urllib.parse

ECCC = 'https://api.weather.gc.ca/collections/climate-daily/items'
STATION = '7027660'
ANNEES = 10


def good(lo, hi):
    return lo is not None and hi is not None and lo <= -2 and 3 <= hi <= 10


def first_flow(days, year):
    """days : {date ISO: (tmin, tmax)} -> date de première coulée du printemps `year`, ou None."""
    keys = sorted(k for k in days if k[:4] == str(year))
    flags, prev_lo = {}, None
    for k in keys:
        lo, hi = days[k]
        night = min([x for x in (prev_lo, lo) if x is not None], default=None)
        flags[k] = good(night, hi)
        prev_lo = lo
    for i, k in enumerate(keys):
        if k[5:] < '02-01' or k[5:] > '04-30' or not flags[k]:
            continue
        window = keys[i:i + 7]
        if sum(flags[x] for x in window) >= 3:
            return dt.date.fromisoformat(k)
    return None


def eccc_month(get_json, year, month):
    q = {'f': 'json', 'CLIMATE_IDENTIFIER': STATION, 'LOCAL_YEAR': year, 'LOCAL_MONTH': month, 'limit': 40,
         'properties': 'LOCAL_DATE,MAX_TEMPERATURE,MIN_TEMPERATURE'}
    out = {}
    for f in get_json(ECCC + '?' + urllib.parse.urlencode(q)).get('features', []):
        p = f['properties']
        if p.get('MAX_TEMPERATURE') is not None and p.get('MIN_TEMPERATURE') is not None:
            out[p['LOCAL_DATE'][:10]] = (p['MIN_TEMPERATURE'], p['MAX_TEMPERATURE'])
    return out


def spring(get_json, climat_month, year):
    """Températures de janvier à avril d'un printemps : ECCC, sinon Climat Québec."""
    days = {}
    for m in (1, 2, 3, 4):
        got = {}
        try:
            got = eccc_month(get_json, year, m)
        except Exception:
            pass
        if len(got) < 20:
            try:
                got = {r['date']: (r['tmin'], r['tmax']) for r in climat_month(year, m) if r.get('tmin') is not None and r.get('tmax') is not None}
            except Exception:
                pass
        days.update(got)
    return days


def mmdd(d):
    return f'{d.month:02d}-{d.day:02d}'


def estimate(get_json, climat_month, saison, annees=ANNEES):
    firsts = {}
    for y in range(saison - annees, saison):
        days = spring(get_json, climat_month, y)
        if len(days) >= 80:  # printemps assez complet
            f = first_flow(days, y)
            if f:
                firsts[y] = f
    if len(firsts) < 5:
        raise ValueError(f'Seulement {len(firsts)} printemps mesurés')
    doy = sorted(f.timetuple().tm_yday for f in firsts.values())
    ref = dt.date(saison, 1, 1)
    as_date = lambda n: ref + dt.timedelta(days=n - 1)
    return {'saison': saison, 'estimation': mmdd(as_date(round(statistics.median(doy)))),
            'plus_tot': mmdd(as_date(doy[0])), 'plus_tard': mmdd(as_date(doy[-1])),
            'annees': {str(y): mmdd(f) for y, f in sorted(firsts.items())}}


def season_for(today):
    """Printemps visé : celui qui suit l'automne en cours (septembre à août)."""
    return today.year + 1 if today.month >= 9 else today.year


def auto(previous, get_json, climat_month, today):
    """Estimation automatique (data/erable-estimation.json) : recalculée seulement si elle ne vise pas
    la saison qui vient. Retourne (estimation, recalculée)."""
    saison = season_for(today)
    if (previous or {}).get('saison') == saison:
        return previous, False
    return {**estimate(get_json, climat_month, saison), 'calcule_le': str(today)}, True


def merge(cfg, est, today):
    """Configuration manuelle (règles, estimation manuelle d'une saison) + estimation automatique -> données de l'appli."""
    saison = season_for(today)
    pc = dict(cfg.get('premiere_coulee', {}))
    man = pc.pop('manuelle', None) or {}
    raisons = []
    if est and est.get('saison') == saison:
        a, b = min(est['annees']), max(est['annees'])
        pc.update({k: est[k] for k in ('saison', 'estimation', 'plus_tot', 'plus_tard', 'annees')})
        raisons.append(f'À Saint-Prosper, la première série de coulées est arrivée entre le {fr(est["plus_tot"])} et le {fr(est["plus_tard"])} '
                       f'sur les printemps {a}–{b} (médiane : {fr(est["estimation"])}). Calcul automatique, refait chaque automne.')
    if man.get('saison') == saison and man.get('date'):
        pc['estimation'], pc['saison'] = man['date'], saison
        raisons.append(man.get('raison') or f'Estimation ajustée à la main pour {saison} : {fr(man["date"])}.')
    raisons.append('On entaille environ 2 semaines avant la première coulée attendue; dès que les prévisions montrent des coulées, la date se recale sur elles.')
    return {**cfg, 'premiere_coulee': pc, 'raisons': raisons}


MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']


def fr(md):
    m, d = (int(x) for x in md.split('-'))
    return f'{d}{"er" if d == 1 else ""} {MOIS[m - 1]}'


if __name__ == '__main__':  # essai manuel : python scripts/erable.py
    import sys, urllib.request
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import collect
    gj = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'DeneigementSaintProsper/1.0'}), timeout=60))
    print(json.dumps(estimate(gj, collect.climat_month, season_for(dt.date.today())), ensure_ascii=False, indent=1))
