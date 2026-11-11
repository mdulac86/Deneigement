"""ECMWF en direct (données ouvertes, CC BY 4.0) : modèle européen IFS et son ensemble.

- IFS déterministe : neige tombée (sf) et précipitations (tp) aux 3 h, sur 72 h.
- Ensemble (51 membres) : pour chaque jour local, probabilité d'avoir 5 cm ou plus,
  et fourchette 10 % / médiane / 90 % des membres.
Seuls les runs de 00 h et 12 h UTC sont utilisés. Un run déjà lu est réutilisé (cache).
La neige est la neige tombée en équivalent eau : 1 mm d'eau ≈ 1 cm de neige (10:1).
"""
import concurrent.futures as futures
import datetime as dt
import statistics

import grib

BASE = 'https://data.ecmwf.int/forecasts'
FALLBACK = 'https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com'
HORIZON = 72
SEUIL = 5


def runs(now):
    t = now.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    t = t.replace(hour=12 if t.hour >= 12 else 0)
    for i in range(4):
        yield t - dt.timedelta(hours=12 * i)


def url(root, run, stream, step):
    d = run.strftime('%Y%m%d')
    kind = 'oper-fc' if stream == 'oper' else 'enfo-ef'
    return f'{root}/{d}/{run:%H}z/ifs/0p25/{stream}/{d}{run:%H}0000-{step}h-{kind}'


def latest_run(now, stream='oper', last_step=HORIZON):
    """Dernier run complètement publié (l'index de la dernière échéance existe)."""
    for run in runs(now):
        for root in (BASE, FALLBACK):
            try:
                grib.get(url(root, run, stream, last_step) + '.index', tries=2)
                return run, root
            except Exception:
                continue
    raise ValueError('Aucun run ECMWF récent disponible')


def deterministic(lat, lon, now):
    grib.warmup()
    run, root = latest_run(now)
    steps = list(range(0, HORIZON + 1, 3))

    def read(step):
        u = url(root, run, 'oper', step)
        idx = grib.ecmwf_index(u + '.index')
        out = {}
        for p in ('tp', 'sf', '2t'):
            e = next((x for x in idx if x.get('param') == p), None)
            out[p] = grib.field(u + '.grib2', e, lat, lon) if e else None
        return step, out

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        vals = dict(pool.map(read, steps))
    hours = []
    for a, b in zip(steps, steps[1:]):
        va, vb = vals[a], vals[b]
        if None in (va['tp'], vb['tp'], va['sf'], vb['sf']):
            continue
        mm = max(0.0, (vb['tp'] - va['tp']) * 1000) / (b - a)
        cm = max(0.0, (vb['sf'] - va['sf']) * 1000) / (b - a)
        temp = None if vb['2t'] is None else round(vb['2t'] - 273.15, 1)
        for k in range(b - a):
            t = run + dt.timedelta(hours=a + k)
            hours.append({'time': t.strftime('%Y-%m-%dT%H:%M:%SZ'), 'precip_mm': round(mm, 2), 'temp': temp, 'snow_cm': round(cm, 2)})
    if len(hours) < 24:
        raise ValueError('Série ECMWF trop courte')
    return {'issued_at': run.strftime('%Y-%m-%dT%H:%M:%SZ'), 'run': run.isoformat(), 'hours': hours,
            'note': 'Modèle européen IFS 0,25° (ECMWF, CC BY 4.0). Neige tombée fournie par le modèle (équivalent eau, 10:1), pas une estimation.'}


def day_windows(run, tz, days=3):
    """Jours locaux couverts, en fenêtres 06 h UTC -> 06 h UTC (1 h -> 1 h HNE), alignées sur les échéances de 3 h."""
    out = []
    first = (run + dt.timedelta(hours=1)).astimezone(tz).date()
    for i in range(days + 1):
        day = first + dt.timedelta(days=i)
        start = dt.datetime.combine(day, dt.time(6), dt.timezone.utc)
        a, b = int((start - run).total_seconds() // 3600), int((start - run).total_seconds() // 3600) + 24
        if a >= 0 and b <= 144 and a % 3 == 0:
            out.append((day, a, b))
    return out[:days]


def ensemble(lat, lon, now, tz):
    grib.warmup()
    run, root = latest_run(now, 'enfo', 90)
    windows = day_windows(run, tz)
    steps = sorted({s for _, a, b in windows for s in (a, b)})

    def members(step):
        u = url(root, run, 'enfo', step)
        idx = [e for e in grib.ecmwf_index(u + '.index') if e.get('param') == 'sf']
        if step == 0:
            return step, {e.get('number', '0'): 0.0 for e in idx}
        with futures.ThreadPoolExecutor(max_workers=8) as pool:
            vals = pool.map(lambda e: (e.get('number', '0'), grib.field(u + '.grib2', e, lat, lon)), idx)
            return step, dict(vals)

    by_step = dict(members(s) for s in steps)
    result = []
    for day, a, b in windows:
        common = set(by_step[a]) & set(by_step[b]) if a else set(by_step[b])
        snow = sorted(max(0.0, (by_step[b][m] - (by_step[a].get(m, 0.0) if a else 0.0)) * 1000) for m in common)
        if len(snow) < 20:
            continue
        q = statistics.quantiles(snow, n=10)
        result.append({'date': str(day), 'membres': len(snow), 'prob_5cm': round(100 * sum(s >= SEUIL for s in snow) / len(snow)),
                       'p10_cm': round(q[0], 1), 'p50_cm': round(statistics.median(snow), 1), 'p90_cm': round(q[-1], 1)})
    if not result:
        raise ValueError('Ensemble ECMWF illisible')
    return {'run': run.isoformat(), 'fenetre': '06 h UTC -> 06 h UTC (1 h -> 1 h HNE)', 'jours': result,
            'note': 'Ensemble ECMWF : 51 versions du modèle européen. Probabilité = part des versions qui donnent 5 cm ou plus.'}


def cached(cache, key, now, fn):
    """Réutilise le résultat si le run n'a pas changé (évite de retélécharger ~25 Mo)."""
    try:
        run, _ = latest_run(now, 'oper' if key == 'ifs' else 'enfo', HORIZON if key == 'ifs' else 90)
    except Exception:
        run = None
    hit = cache.get(key)
    if hit and run and hit.get('run') == run.isoformat():
        return hit['result'], False
    result = fn()
    cache[key] = {'run': result.get('run'), 'result': result}
    return result, True
