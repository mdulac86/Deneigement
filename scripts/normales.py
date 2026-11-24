"""Normale « à pareille date » pour l'onglet Mon hiver : moyenne, à chaque date du 1er octobre au 31 mai,
des cumuls depuis le 1er octobre, sur les 15 hivers les plus récents dont les relevés sont complets : l'hiver d'aujourd'hui
n'est plus celui des années 1970 (2011-2012, 2012-2013 et 2024-2025 ont trop de jours manquants). Station ST PROSPER 7027660 : Environnement Canada jusqu'en septembre 2024,
puis relevés Climat Québec (data/season-AAAA.json, mêmes chiffres de la même station).

Mêmes règles que l'onglet (observedSeason dans app.js) :
- tempêtes : épisodes de neige (pause d'un jour au plus) de 5 cm et plus, de 15 cm et plus;
- jours de déneigement : 2 cm accumulés à la station (≈ 5 cm dans les stationnements; environ 30 jours par hiver,
  comme le constate l'équipe); les petites chutes s'additionnent jusqu'à un redoux de 4 °C ou 2 mm de pluie;
- fontes sur la neige au sol (slush) : début d'un redoux (4 °C et plus ou 5 mm de pluie) avec 5 cm et plus au sol;
- verglas probable : 1 mm de pluie et plus, min -1 °C et moins, max 2 °C et moins;
- pluie d'hiver : 2 mm et plus, de décembre à mars.

Lancé à la main (le résultat ne change pas d'un jour à l'autre) : python scripts/normales.py
Écrit data/normale-par-date.json.
"""
import datetime as dt
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://api.weather.gc.ca/collections/climate-daily/items'
STATION = '7027660'
PREMIER, DERNIER = 1995, 2025  # on remonte depuis 2025-2026 jusqu'à trouver NB hivers complets
NB = 15
SEUIL_STATION_CM = 2  # jours de déneigement (voir cumuls)
RATIO_STATIONNEMENT = 2.5  # 2 cm à la station ≈ 5 cm dans les stationnements
HEURES_SLUSH = 4  # une tournée de nettoyage de slush
HEURES_NORMALES = 225  # heures-machine d'un hiver normal (constat de l'équipe) : calibre les heures estimées


def duree_h(cm):
    """Règle de config/plan.json : 4 h jusqu'à 10 cm, +1,5 h par tranche de 10 cm de plus."""
    return 4 if cm <= 10 else 4 + 1.5 * -(-(cm - 10) // 10)
COUVERTURE = 0.85  # un hiver compte s'il a au moins 85 % des jours de neige renseignés de novembre à avril


def fetch_all():
    rows, offset = [], 0
    props = 'LOCAL_DATE,TOTAL_SNOW,TOTAL_RAIN,MAX_TEMPERATURE,MIN_TEMPERATURE,SNOW_ON_GROUND'
    while True:
        q = (f'{URL}?f=json&CLIMATE_IDENTIFIER={STATION}&datetime={PREMIER}-10-01/{DERNIER + 1}-05-31'
             f'&properties={props}&sortby=LOCAL_DATE&limit=10000&offset={offset}')
        with urllib.request.urlopen(urllib.request.Request(q, headers={'User-Agent': 'deneigement-normales'}), timeout=120) as r:
            feats = json.load(r)['features']
        for f in feats:
            p = f['properties']
            rows.append({'date': p['LOCAL_DATE'][:10], 'snow_cm': p['TOTAL_SNOW'], 'rain_mm': p['TOTAL_RAIN'],
                         'tmax': p['MAX_TEMPERATURE'], 'tmin': p['MIN_TEMPERATURE'], 'depth_cm': p['SNOW_ON_GROUND']})
        if len(feats) < 10000:
            return rows
        offset += 10000


def cumuls(records):
    """Cumuls depuis le 1er octobre jusqu'à la dernière ligne de records (mêmes règles que app.js)."""
    rows = sorted((r for r in records if r['snow_cm'] is not None), key=lambda r: r['date'])
    eps, cur, last = [], None, None
    for r in rows:
        if r['snow_cm'] < 0.2:
            continue
        t = dt.date.fromisoformat(r['date'])
        if cur and (t - last).days > 2:
            eps.append(cur)
            cur = None
        cur = cur or {'total': 0.0}
        cur['total'] += r['snow_cm']
        last = t
    if cur:
        eps.append(cur)
    # Jours de déneigement : 2 cm accumulés à la station (calibré sur la réalité de l'équipe : environ 30 jours
    # par hiver; la station mesure moins que ce qui s'accumule dans les stationnements).
    acc, jours, heures = 0.0, 0, 0.0
    for r in rows:
        s, rain = r['snow_cm'], r['rain_mm'] or 0
        if rain >= 5:
            acc = 0
            continue
        if s >= 0.2:
            acc += s
        elif (r['tmax'] is not None and r['tmax'] >= 4) or rain >= 2:
            acc = 0
        if acc >= SEUIL_STATION_CM:
            jours += 1
            heures += duree_h(acc * RATIO_STATIONNEMENT)
            acc = 0
    # Fontes sur la neige au sol (slush à nettoyer) : début d'un redoux (max 4 °C et plus ou 5 mm de pluie)
    # avec 5 cm et plus de neige au sol (mesurée, sinon estimée).
    fonte, ground, warm_prev = 0, 0.0, False
    for r in sorted(records, key=lambda r: r['date']):
        tx, rain, d = r['tmax'], r['rain_mm'] or 0, r.get('depth_cm')
        ground = d if d is not None else ground + (r['snow_cm'] or 0)
        warm = (tx is not None and tx >= 4) or rain >= 5
        if warm and ground >= 5 and not warm_prev:
            fonte += 1
            heures += HEURES_SLUSH
        warm_prev = warm
        if d is None and tx is not None and tx > 0:
            ground = max(0.0, ground - tx * 0.5 - rain * 0.5)
    verglas = pluie = 0
    for r in records:
        rain = r['rain_mm']
        if rain is None or r['tmax'] is None or r['tmin'] is None:
            continue
        if rain >= 1 and r['tmin'] <= -1 and r['tmax'] <= 2:
            verglas += 1
        elif rain >= 2 and r['date'][5:7] in ('12', '01', '02', '03'):
            pluie += 1
    return {'neige_cm': sum(r['snow_cm'] for r in rows), 'tempetes_5cm': sum(e['total'] >= 5 for e in eps),
            'tempetes_15cm': sum(e['total'] >= 15 for e in eps), 'jours_deneigement': jours,
            'sorties_fonte': fonte, 'jours_verglas': verglas, 'jours_pluie': pluie, 'heures_brutes': heures}


def season_days(y):
    d, out = dt.date(y, 10, 1), []
    while d <= dt.date(y + 1, 5, 31):
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def main():
    rows = fetch_all()
    by_date = {r['date']: r for r in rows}
    for f in sorted((ROOT / 'data').glob('season-*.json')):  # Climat Québec après Environnement Canada
        for r in json.loads(f.read_text(encoding='utf-8')).get('records', []):
            if r['date'] not in by_date or by_date[r['date']]['snow_cm'] is None:
                by_date[r['date']] = {k: r.get(k) for k in ('date', 'snow_cm', 'rain_mm', 'tmax', 'tmin')}
    sums, used = {}, []
    for y in range(DERNIER, PREMIER - 1, -1):
        if len(used) >= NB:
            break
        days = season_days(y)
        recs = [by_date[str(d)] for d in days if str(d) in by_date]
        core = [d for d in days if d.month in (11, 12, 1, 2, 3, 4)]
        if sum(by_date.get(str(d), {}).get('snow_cm') is not None for d in core) < COUVERTURE * len(core):
            continue
        used.append(y)
        i = 0
        for d in days:
            while i < len(recs) and recs[i]['date'] <= str(d):
                i += 1
            if d.month == 2 and d.day == 29:
                continue
            c = cumuls(recs[:i])
            e = sums.setdefault(d.strftime('%m-%d'), {})
            for k, v in c.items():
                e[k] = e.get(k, 0) + v
    n = len(used)
    k_h = HEURES_NORMALES / (sums['05-31']['heures_brutes'] / n)  # facteur : la normale au 31 mai = 225 h
    par_date = {}
    for d, v in sums.items():
        e = {kk: round(vv / n, 1) for kk, vv in v.items() if kk != 'heures_brutes'}
        e['heures'] = round(v['heures_brutes'] / n * k_h)
        par_date[d] = e
    used.sort()
    out = {'periode': f'{n} hivers récents ({used[0]}-{used[0] + 1} à {used[-1]}-{used[-1] + 1}, relevés complets), station ST PROSPER 7027660',
           'source': 'Environnement Canada, données climatiques quotidiennes', 'hivers': n,
           'regle': 'Moyenne des cumuls depuis le 1er octobre à chaque date; mêmes règles que l’onglet.',
           'heures': {'facteur': round(k_h, 3), 'ratio_stationnement': RATIO_STATIONNEMENT, 'heures_slush': HEURES_SLUSH,
                      'regle': f'Heures-machine estimées : règle du plan par jour de déneigement (cm de la station × {RATIO_STATIONNEMENT}), {HEURES_SLUSH} h par fonte, × {k_h:.2f} pour qu’un hiver normal fasse {HEURES_NORMALES} h.'},
           'par_date': par_date}
    (ROOT / 'data' / 'normale-par-date.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(out['periode'], '| hivers :', used, '| 31 mai :', par_date['05-31'], '| 24 nov. :', par_date['11-24'])


if __name__ == '__main__':
    main()
