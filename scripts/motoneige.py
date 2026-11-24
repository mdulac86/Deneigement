"""Motoneige hors-piste : où rouler la fin de semaine, et est-ce que ça vaut la route ?

Pour chaque endroit (config/motoneige.json) :
- neige au sol maintenant : modèle canadien HRDPS (GeoMet, SD en m) et HRRR (SNOD, m), médiane;
- 7 jours de prévisions par tranche de 6 h : synthèse américaine NBM (neige tombée, précipitations,
  température, rafales). NBM est la source la plus fiable mesurée à Saint-Prosper (trust.py);
- historique de la neige au sol (data/motoneige.json) : variation sur 72 h.

Projection de la base : + neige fraîche (tassée de 20 %), - fonte (0,4 cm par °C au-dessus de 0
par tranche de 6 h), - pluie sur la neige (0,3 cm par mm).
Surface du jour : poudreuse, neige fraîche, bonne base, ventée/tapée, lourde (redoux), croûte/glacée
(dégel ou pluie puis regel sans neige fraîche par-dessus).
Note de 0 à 10 : base (0 à 5) + surface (-2 à +4) - pluie dans la journée.
« Vaut la route » : note moins 1 point par heure de route au-delà de la première.
Valeurs au point de grille (2,5 km) : pas sous le couvert forestier ni au sommet exact.
Fonctions de calcul pures (testées dans tests/test_motoneige.py); lecture réseau dans collect().
"""
import concurrent.futures as futures
import datetime as dt
import statistics

import grib
import noaa

HORIZON_H = 168
FONTE_CM_PAR_C = 0.4  # par tranche de 6 h et par °C au-dessus de 0
PLUIE_CM_PAR_MM = 0.3
TASSEMENT = 0.8


def nbm_run_7days(now):
    """Dernier cycle NBM dont l'échéance de 168 h est publiée (le cycle en cours peut être incomplet)."""
    for run in noaa.cycles(now, back=10):
        try:
            for f in (HORIZON_H, 12):
                grib.get(noaa.nbm_url(run, f) + '.idx', tries=2)
            return run
        except Exception:
            continue
    raise ValueError('Aucun cycle NBM de 7 jours disponible')


def nbm_windows(pts, now):
    """[{'debut', 'fin', 'snow_cm', 'precip_mm', 'temp', 'gust_kmh'} par point] sur 7 jours (NBM, tranches de 6 h)."""
    grib.warmup()
    run = nbm_run_7days(now)
    first = 6 + (-(run.hour + 6)) % 6
    steps = list(range(first, HORIZON_H + 1, 6))

    def read(f):
        url = noaa.nbm_url(run, f)
        try:
            rows = noaa.index(url)
        except FileNotFoundError:  # tranche pas encore publiée : laissée vide
            return f, {k: [None] * len(pts) for k in ('snow', 'apcp', 'tmp', 'gust')}
        win = f'{f - 6}-{f} hour acc fcst'
        get = lambda key: (lambda e: grib.field_points(url, e, pts) if e else [None] * len(pts))(noaa.pick(rows, key))
        return f, {'snow': get(f'ASNOW:surface:{win}'), 'apcp': get(f'APCP:surface:{win}'),
                   'tmp': get(f'TMP:2 m above ground:{f} hour fcst'), 'gust': get(f'GUST:10 m above ground:{f} hour fcst')}

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        vals = dict(pool.map(read, steps))
    out = [[] for _ in pts]
    for f in steps:
        v, start = vals[f], run + dt.timedelta(hours=f - 6)
        for i in range(len(pts)):
            s, p, t, g = v['snow'][i], v['apcp'][i], v['tmp'][i], v['gust'][i]
            out[i].append({'debut': start.isoformat(), 'fin': (start + dt.timedelta(hours=6)).isoformat(),
                           'snow_cm': None if s is None else round(max(0.0, noaa.to_cm(s)), 1),
                           'precip_mm': None if p is None else round(max(0.0, p), 1),
                           'temp': None if t is None else round(t - 273.15, 1),
                           'gust_kmh': None if g is None else round(g * 3.6)})
    return run, out


def depth_now(fetch_json, nwp, pts, now):
    """Neige au sol (cm) : HRDPS (GeoMet) et HRRR (dernier run horaire), par point."""
    hrdps = [None] * len(pts)
    try:
        times, ref = nwp.capabilities(fetch_json, 'HRDPS.CONTINENTAL_SD')
        t = min(times, key=lambda x: abs((x - now).total_seconds()))
        for i, (la, lo) in enumerate(pts):
            v = nwp.feature_value(fetch_json, 'HRDPS.CONTINENTAL_SD', t, ref, la, lo)
            hrdps[i] = round((v or 0.0) * 100, 1)  # m -> cm; pas de valeur = pas de neige
    except Exception as e:
        print('motoneige HRDPS :', str(e)[:100])
    hrrr = [None] * len(pts)
    try:
        run = noaa.hrrr_run(now, noaa.HRRR_RAPIDE)
        url = noaa.hrrr_url(run, 1)
        e = noaa.pick(noaa.index(url), 'SNOD:surface:1 hour fcst')
        if e:
            hrrr = [round(v * 100, 1) for v in grib.field_points(url, e, pts)]
    except Exception as e:
        print('motoneige HRRR :', str(e)[:100])
    out = []
    for a, b in zip(hrdps, hrrr):
        vals = [x for x in (a, b) if x is not None]
        out.append({'hrdps': a, 'hrrr': b, 'cm': round(statistics.mean(vals), 1) if vals else None})
    return out


def base_points(cm):
    for lim, pts in ((70, 5), (50, 4), (35, 3), (25, 2), (15, 1)):
        if cm >= lim:
            return pts
    return 0


SURFACE = {'Poudreuse': 4, 'Neige fraîche': 2, 'Bonne base': 1, 'Ventée / tapée': 0, 'Lourde (redoux)': -1,
           'Croûte / glacée': -2, 'Base mince': 0, 'Pas de neige': 0}


def local_date(iso, tz):
    return dt.datetime.fromisoformat(iso).astimezone(tz).date()


def days_for(depth_cm, windows, tz):
    """Projection jour par jour (jours locaux) : base, neige fraîche 48 h, surface, note."""
    depth = depth_cm or 0.0
    hist, out = [], {}
    for w in windows:
        s, p, t = w['snow_cm'] or 0.0, w['precip_mm'] or 0.0, w['temp']
        rain = p if (t is not None and t > 0.5) else max(0.0, p - s)  # au-dessus de 0,5 °C : pluie
        depth += TASSEMENT * s
        if t is not None and t > 0:
            depth -= FONTE_CM_PAR_C * t
        depth -= PLUIE_CM_PAR_MM * rain if depth > 0 else 0
        depth = max(0.0, depth)
        hist.append({**w, 'rain_mm': round(rain, 1), 'depth': depth})
    for i, w in enumerate(hist):
        d = local_date(w['debut'], tz)
        h = dt.datetime.fromisoformat(w['debut']).astimezone(tz).hour
        if d not in out:
            out[d] = []
        out[d].append((i, h, w))
    result = []
    for d, items in sorted(out.items()):
        idx = [i for i, _, _ in items]
        day_w = [w for _, h, w in items if 6 <= h < 18] or [w for _, _, w in items]
        noon = day_w[-1]
        end = max(idx)
        before = hist[max(0, end - 7):end + 1]  # ~48 h jusqu'à la fin de la journée
        fresh = sum(x['snow_cm'] or 0 for x in before)
        temps = [x['temp'] for x in day_w if x['temp'] is not None]
        tmax = max(temps) if temps else None
        rain_day = sum(x['rain_mm'] for x in day_w)
        gust = max((x['gust_kmh'] or 0 for x in hist[max(0, end - 4):end + 1]), default=0)
        prev = hist[max(0, end - 12):max(0, end - 1)]  # 72 h avant
        thaw = any((x['temp'] or -9) > 0.5 or x['rain_mm'] >= 1 for x in prev)
        refreeze = any((x['temp'] or 9) < -2 for x in hist[max(0, end - 6):end + 1])
        base = noon['depth']
        if base < 5:
            surf = 'Pas de neige'
        elif tmax is not None and tmax > 1:
            surf = 'Lourde (redoux)'
        elif fresh >= 10:
            surf = 'Poudreuse'
        elif thaw and refreeze and fresh < 5:
            surf = 'Croûte / glacée'
        elif fresh >= 3:
            surf = 'Neige fraîche'
        elif gust >= 50:
            surf = 'Ventée / tapée'
        elif base < 25:
            surf = 'Base mince'
        else:
            surf = 'Bonne base'
        score = base_points(base) + SURFACE[surf] - (2 if rain_day >= 2 else 1 if rain_day >= 0.5 else 0)
        if base < 15:
            score = min(score, 2)  # roches et souches : pas de hors-piste
        result.append({'date': str(d), 'base_cm': round(base), 'fraiche_48h_cm': round(fresh, 1), 'surface': surf,
                       'note': max(0, min(10, score)), 'tmax': tmax, 'pluie_mm': round(rain_day, 1), 'rafales_kmh': gust or None})
    return result


def worth(note, route_min):
    """Note moins 1 point par heure de route au-delà de la première."""
    return round(note - max(0.0, route_min / 60 - 1), 1)


def weekend(days, today):
    """Samedi et dimanche qui viennent (ou aujourd'hui si on y est)."""
    sat = today + dt.timedelta(days=(5 - today.weekday()) % 7)
    want = {str(sat), str(sat + dt.timedelta(days=1))}
    return [d for d in days if d['date'] in want]


def change_72h(history, spot_id, now_cm, now):
    old = [h for h in history if spot_id in h.get('cm', {}) and
           dt.datetime.fromisoformat(h['time']) <= now - dt.timedelta(hours=66)]
    if now_cm is None or not old:
        return None
    return round(now_cm - old[-1]['cm'][spot_id], 1)


def in_season(cfg, today):
    a, b = (int(x.replace('-', '')) for x in (cfg['saison']['debut'], cfg['saison']['fin']))
    md = today.month * 100 + today.day
    return md >= a or md <= b


def collect(cfg, fetch_json, nwp, now, tz, history):
    spots = cfg['endroits']
    pts = [(s['lat'], s['lon']) for s in spots]
    run, wins = nbm_windows(pts, now)
    depths = depth_now(fetch_json, nwp, pts, now)
    today = now.astimezone(tz).date()
    history = [h for h in history if dt.datetime.fromisoformat(h['time']) >= now - dt.timedelta(days=14)]
    history.append({'time': now.isoformat(), 'cm': {s['id']: d['cm'] for s, d in zip(spots, depths) if d['cm'] is not None}})
    out = []
    for s, d, w in zip(spots, depths, wins):
        days = days_for(d['cm'], w, tz)
        we = weekend(days, today)
        best = max(we, key=lambda x: x['note']) if we else None
        out.append({**s, 'neige_sol': d, 'variation_72h_cm': change_72h(history[:-1], s['id'], d['cm'], now),
                    'jours': days, 'fin_de_semaine': we,
                    'vaut_la_route': worth(best['note'], s['route_min']) if best else None})
    ranked = sorted([o for o in out if o['vaut_la_route'] is not None], key=lambda o: -o['vaut_la_route'])
    return {'status': 'ok', 'run_nbm': run.isoformat(), 'mis_a_jour': now.isoformat(), 'endroits': out,
            'classement': [o['id'] for o in ranked],
            'note': 'Neige au sol : HRDPS (Environnement Canada) et HRRR (NOAA). Prévisions : NBM (NOAA), tranches de 6 h sur 7 jours. '
                    'Valeurs au point de grille de 2,5 km, pas sous le couvert forestier : à confirmer sur place.'}, history
