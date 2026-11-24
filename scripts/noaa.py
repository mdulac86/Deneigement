"""Modèles américains en données ouvertes (NOAA, domaine public) au point de Saint-Prosper.

Saint-Prosper est à 25 km de la frontière du Maine : il est dans la grille « CONUS » des
produits américains (point de grille le plus proche à 1 km environ).

- NBM (National Blend of Models, 2,5 km) : synthèse officielle d'une trentaine de modèles,
  corrigée statistiquement. Neige tombée par tranche de 6 h jusqu'à 72 h, et surtout la
  PROBABILITÉ de dépasser 2,5 cm et 5 cm (1 po et 2 po) par tranche de 6 h jusqu'à 48 h.
- HRRR (3 km) : modèle à haute résolution relancé chaque heure. Neige tombée heure par heure
  sur 48 h (runs de 00, 06, 12 et 18 UTC), température et pluie verglaçante prévue.

Lecture par plages d'octets dans les archives Amazon (NOAA Open Data Dissemination),
comme pour GFS et ECMWF (voir grib.py). Neige fournie par les modèles, pas estimée.
"""
import concurrent.futures as futures
import datetime as dt

import grib

NBM = 'https://noaa-nbm-grib2-pds.s3.amazonaws.com'
HRRR = 'https://noaa-hrrr-bdp-pds.s3.amazonaws.com'
NBM_HORIZON = 72
NBM_PROBA_HORIZON = 48
HRRR_HORIZON = 48
HRRR_STEPS = list(range(1, 25)) + list(range(27, HRRR_HORIZON + 1, 3))
SEUILS_M = {'p_2_5cm': '0.0254', 'p_5cm': '0.0508'}  # seuils NBM en mètres (1 po, 2 po)


def zulu(t):
    return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def index(url):
    """Index NOAA (.idx) -> liste de dict avec la description complète (y compris le seuil de probabilité)."""
    lines = [l for l in grib.get(url + '.idx').decode().splitlines() if l.strip()]
    rows = []
    for line in lines:
        p = line.split(':')
        if len(p) >= 6:
            rows.append({'_offset': int(p[1]), 'key': ':'.join(p[3:]).rstrip(':')})
    for a, b in zip(rows, rows[1:]):
        a['_length'] = b['_offset'] - a['_offset']
    if rows:
        rows[-1]['_length'] = 5_000_000
    return rows


def pick(rows, key):
    """Champ dont la description est exactement `key` (ex. 'ASNOW:surface:6-12 hour acc fcst')."""
    return next((r for r in rows if r['key'] == key), None)


def value(url, entry, lat, lon):
    v, unit = grib.field(url, entry, lat, lon, units=True)
    return v, unit


def to_cm(v, unit):
    return v * 100 if unit.strip() == 'm' else v


def cycles(now, step=1, back=8):
    t = now.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    t -= dt.timedelta(hours=t.hour % step)
    for i in range(back):
        yield t - dt.timedelta(hours=step * i)


def nbm_url(run, f):
    return f'{NBM}/blend.{run:%Y%m%d}/{run:%H}/core/blend.t{run:%H}z.core.f{f:03d}.co.grib2'


def nbm_run(now):
    """Dernier cycle NBM publié jusqu'à 72 h."""
    for run in cycles(now):
        try:
            grib.get(nbm_url(run, NBM_HORIZON) + '.idx', tries=2)
            return run
        except Exception:
            continue
    raise ValueError('Aucun cycle NBM récent disponible')


def nbm(lat, lon, now):
    """Neige NBM par tranche de 6 h et probabilités de 2,5 cm et 5 cm."""
    grib.warmup()
    run = nbm_run(now)
    # Les tranches de 6 h (quantités et probabilités) se terminent à 00, 06, 12 ou 18 UTC.
    first = 6 + (-(run.hour + 6)) % 6
    steps = list(range(first, NBM_HORIZON + 1, 6))

    def read(f):
        url = nbm_url(run, f)
        rows = index(url)
        win = f'{f - 6}-{f} hour acc fcst'
        out = {'f': f}
        e = pick(rows, f'ASNOW:surface:{win}')
        out['snow_cm'] = round(max(0.0, to_cm(*value(url, e, lat, lon))), 1) if e else None
        e = pick(rows, f'APCP:surface:{win}')
        out['precip_mm'] = round(max(0.0, value(url, e, lat, lon)[0]), 1) if e else None
        e = pick(rows, f'TMP:2 m above ground:{f} hour fcst')
        out['temp'] = round(value(url, e, lat, lon)[0] - 273.15, 1) if e else None
        if f <= NBM_PROBA_HORIZON:
            for k, thr in SEUILS_M.items():
                e = pick(rows, f'ASNOW:surface:{win}:prob >{thr}:prob fcst 255/255')
                out[k] = round(value(url, e, lat, lon)[0]) if e else None
        return out

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        blocks = sorted(pool.map(read, steps), key=lambda b: b['f'])
    tranches, hours = [], []
    for b in blocks:
        start = run + dt.timedelta(hours=b['f'] - 6)
        tranches.append({'debut': zulu(start), 'fin': zulu(start + dt.timedelta(hours=6)), 'snow_cm': b['snow_cm'],
                         'precip_mm': b['precip_mm'], 'temp': b['temp'], 'p_2_5cm': b.get('p_2_5cm'), 'p_5cm': b.get('p_5cm')})
        if b['snow_cm'] is None:
            continue
        for k in range(6):  # tranche de 6 h répartie également sur chaque heure (comme MétéoMédia)
            hours.append({'time': zulu(start + dt.timedelta(hours=k)), 'snow_cm': round(b['snow_cm'] / 6, 2),
                          'precip_mm': None if b['precip_mm'] is None else round(b['precip_mm'] / 6, 2), 'temp': b['temp']})
    if len(hours) < 24:
        raise ValueError('Série NBM trop courte')
    return {'issued_at': zulu(run), 'run': run.isoformat(), 'hours': hours, 'tranches': tranches,
            'note': 'NBM (NOAA) : synthèse corrigée d’une trentaine de modèles. Neige fournie par tranche de 6 h, '
                    'répartie également sur chaque heure. Probabilités de 2,5 cm et 5 cm par tranche de 6 h jusqu’à 48 h.'}


def hrrr_url(run, f):
    return f'{HRRR}/hrrr.{run:%Y%m%d}/conus/hrrr.t{run:%H}z.wrfsfcf{f:02d}.grib2'


def hrrr_run(now):
    """Dernier run HRRR de 48 h (00, 06, 12 ou 18 UTC) entièrement publié."""
    for run in cycles(now, step=6, back=4):
        try:
            grib.get(hrrr_url(run, HRRR_HORIZON) + '.idx', tries=2)
            return run
        except Exception:
            continue
    raise ValueError('Aucun run HRRR de 48 h disponible')


def hrrr(lat, lon, now):
    """Neige, précipitations, température et pluie verglaçante heure par heure (HRRR)."""
    grib.warmup()
    run = hrrr_run(now)

    def read(f):
        url = hrrr_url(run, f)
        rows = index(url)
        out = {'f': f}
        acc = f'0-{f // 24} day acc fcst' if f % 24 == 0 else f'0-{f} hour acc fcst'  # « 0-1 day » à 24 h
        e = pick(rows, f'ASNOW:surface:{acc}')
        out['snow'] = to_cm(*value(url, e, lat, lon)) if e else None
        e = pick(rows, f'APCP:surface:{acc}')
        out['precip'] = value(url, e, lat, lon)[0] if e else None
        e = pick(rows, f'TMP:2 m above ground:{f} hour fcst')
        out['temp'] = round(value(url, e, lat, lon)[0] - 273.15, 1) if e else None
        e = pick(rows, f'CFRZR:surface:{f} hour fcst')
        out['verglas'] = (value(url, e, lat, lon)[0] >= 0.5) if e else None
        return out

    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        vals = {v['f']: v for v in pool.map(read, HRRR_STEPS)}
    vals[0] = {'f': 0, 'snow': 0.0, 'precip': 0.0}
    steps = [0] + HRRR_STEPS
    hours = []
    for a, b in zip(steps, steps[1:]):
        va, vb = vals[a], vals[b]
        if None in (va.get('snow'), vb.get('snow'), va.get('precip'), vb.get('precip')):
            continue
        span = b - a
        cm = max(0.0, vb['snow'] - va['snow']) / span
        mm = max(0.0, vb['precip'] - va['precip']) / span
        for k in range(span):
            hours.append({'time': zulu(run + dt.timedelta(hours=a + k)), 'snow_cm': round(cm, 2), 'precip_mm': round(mm, 2),
                          'temp': vb['temp'], 'verglas': bool(vb.get('verglas'))})
    if len(hours) < 12:
        raise ValueError('Série HRRR trop courte')
    return {'issued_at': zulu(run), 'run': run.isoformat(), 'hours': hours,
            'note': 'HRRR (NOAA, 3 km) : neige tombée fournie par le modèle, heure par heure jusqu’à 24 h puis par 3 h '
                    'jusqu’à 48 h. Signale aussi la pluie verglaçante prévue.'}
