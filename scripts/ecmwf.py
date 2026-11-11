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


def url(root, run, stream, step, model='ifs'):
    d = run.strftime('%Y%m%d')
    kind = 'oper-fc' if stream == 'oper' else 'enfo-ef'
    return f'{root}/{d}/{run:%H}z/{model}/0p25/{stream}/{d}{run:%H}0000-{step}h-{kind}'


def latest_run(now, stream='oper', last_step=HORIZON, model='ifs'):
    """Dernier run complètement publié (l'index de la dernière échéance existe)."""
    for run in runs(now):
        for root in (BASE, FALLBACK):
            try:
                grib.get(url(root, run, stream, last_step, model) + '.index', tries=2)
                return run, root
            except Exception:
                continue
    raise ValueError('Aucun run ECMWF récent disponible')


LONG = 360  # 15 jours : tendance à long terme


def steps_for(model, horizon=LONG):
    if model == 'ifs':  # aux 3 h jusqu'à 144 h, puis aux 6 h
        return list(range(0, min(horizon, 144) + 1, 3)) + list(range(150, horizon + 1, 6))
    return list(range(0, horizon + 1, 6))


def deterministic(lat, lon, now, model='ifs', horizon=LONG):
    """IFS ou AIFS (modèle européen à intelligence artificielle), jusqu'à 15 jours."""
    grib.warmup()
    run, root = latest_run(now, model=model, last_step=horizon)
    steps = steps_for(model, horizon)

    def read(step):
        u = url(root, run, 'oper', step, model)
        idx = grib.ecmwf_index(u + '.index')
        out = {}
        for p in ('tp', 'sf', '2t'):
            e = next((x for x in idx if x.get('param') == p), None)
            if e is None:
                out[p] = None
            elif p == '2t':
                out[p] = grib.field(u + '.grib2', e, lat, lon)
            else:
                v, unit = grib.field(u + '.grib2', e, lat, lon, units=True)
                out[p] = grib.to_mm(v, unit)
        return step, out

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        vals = dict(pool.map(read, steps))
    hours = []
    for a, b in zip(steps, steps[1:]):
        va, vb = vals[a], vals[b]
        if None in (va['tp'], vb['tp'], va['sf'], vb['sf']):
            continue
        mm = max(0.0, vb['tp'] - va['tp']) / (b - a)
        cm = max(0.0, vb['sf'] - va['sf']) / (b - a)
        temp = None if vb['2t'] is None else round(vb['2t'] - 273.15, 1)
        for k in range(b - a):
            t = run + dt.timedelta(hours=a + k)
            hours.append({'time': t.strftime('%Y-%m-%dT%H:%M:%SZ'), 'precip_mm': round(mm, 2), 'temp': temp, 'snow_cm': round(cm, 2)})
    if len(hours) < 24:
        raise ValueError('Série ECMWF trop courte')
    label = 'IFS 0,25°' if model == 'ifs' else 'AIFS (intelligence artificielle) 0,25°'
    return {'issued_at': run.strftime('%Y-%m-%dT%H:%M:%SZ'), 'run': run.isoformat(), 'hours': hours,
            'note': f'Modèle européen {label} (ECMWF, CC BY 4.0). Neige tombée fournie par le modèle (équivalent eau, 10:1), pas une estimation.'}


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
        if key == 'ens':
            run, _ = latest_run(now, 'enfo', 90)
        elif key == 'pop':
            run, _ = latest_run(now, 'enfo', 90)
        else:
            run, _ = latest_run(now, model='aifs-single' if key == 'aifs' else 'ifs', last_step=LONG)
    except Exception:
        run = None
    hit = cache.get(key)
    short = key in ('ifs', 'aifs') and hit and len(hit.get('result', {}).get('hours', [])) < 300  # ancien cache de 72 h
    if hit and run and hit.get('run') == run.isoformat() and not short:
        return hit['result'], False
    result = fn()
    cache[key] = {'run': result.get('run'), 'result': result}
    return result, True


def precip_probability(lat, lon, now, tz, days=15):
    """Probabilités de précipitations de l'ensemble (produit « ep ») : 1 mm, 5 mm et 10 mm et plus
    en 24 h, pour chaque jour, fenêtre 12 h UTC -> 12 h UTC (7 h -> 7 h, heure normale)."""
    grib.warmup()
    run, root = latest_run(now, 'enfo', 90)
    d = run.strftime('%Y%m%d')
    entries = []
    for last in (240, 360):
        base = f'{root}/{d}/{run:%H}z/ifs/0p25/enfo/{d}{run:%H}0000-{last}h-enfo-ep'
        try:
            entries += [(base, e) for e in grib.ecmwf_index(base + '.index') if e.get('param') in ('tpg1', 'tpg5', 'tpg10')]
        except FileNotFoundError:
            continue
    by_window = {}
    for base, e in entries:
        a, b = (int(x) for x in str(e['step']).split('-'))
        if b - a == 24:
            by_window.setdefault(a, {})[e['param']] = (base, e)
    out = []
    first = (run + dt.timedelta(hours=1)).astimezone(tz).date()
    for i in range(days):
        day = first + dt.timedelta(days=i)
        start = dt.datetime.combine(day, dt.time(12), dt.timezone.utc)
        a = int((start - run).total_seconds() // 3600)
        w = by_window.get(a)
        if not w or 'tpg1' not in w:
            continue
        vals = {p: round(grib.field(base + '.grib2', e, lat, lon)) for p, (base, e) in w.items()}
        out.append({'date': str(day), 'p1': vals.get('tpg1'), 'p5': vals.get('tpg5'), 'p10': vals.get('tpg10')})
    if not out:
        raise ValueError('Probabilités ECMWF illisibles')
    return {'run': run.isoformat(), 'fenetre': '12 h UTC -> 12 h UTC (7 h -> 7 h)', 'jours': out}
