"""Modèles numériques horaires, gratuits et libres pour un usage commercial.

- ECCC HRDPS (2,5 km, ~48 h) et RDPS (10 km, ~72 h ici) via MSC GeoMet (WMS GetFeatureInfo).
- MET Norway Locationforecast (déjà collecté par collect.py).
- NOAA GFS 0,25° via THREDDS NCSS (UCAR).

Toutes ces sources donnent des précipitations (mm d'eau) et la température. Les cm de
neige sont une ESTIMATION : mm × rapport neige/eau selon la température, signalée
comme telle dans l'interface. Une valeur absente reste None.
"""
import concurrent.futures as futures
import csv
import datetime as dt
import io
import json
import urllib.parse
import xml.etree.ElementTree as ET

GEOMET = 'https://geo.weather.gc.ca/geomet'
THREDDS = 'https://thredds.ucar.edu/thredds/ncss/grid/grib/NCEP/GFS/Global_0p25deg/Best'
HORIZON_H = 72

ECCC_MODELS = {
    'hrdps': ('HRDPS 2,5 km · ECCC', ['HRDPS.CONTINENTAL_PR'], ['HRDPS.CONTINENTAL_TT'], 48),
    'rdps': ('RDPS 10 km · ECCC', ['RDPS.ETA_PR', 'RDPS.CONTINENTAL_PR'], ['RDPS.ETA_TT', 'RDPS.CONTINENTAL_TT'], HORIZON_H),
}


def snow_from_precip(mm, temp):
    """cm de neige estimés. 10:1 près de 0 °C, plus léger au froid, mélange de 0,5 à 2 °C."""
    if mm is None or temp is None:
        return None
    if mm <= 0 or temp >= 2:
        return 0.0
    if temp > 0.5:
        return round(mm * (2 - temp) / 1.5 * 0.8, 2)
    ratio = 10 if temp > -2 else 13 if temp > -8 else 15
    return round(mm * ratio / 10, 2)


def utc(text):
    return dt.datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(dt.timezone.utc)


def zulu(t):
    return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_times(text):
    text = text.strip()
    parts = text.split('/')
    if len(parts) == 3:
        start, end, step = utc(parts[0]), utc(parts[1]), parts[2]
        hours = int(step.removeprefix('PT').removesuffix('H')) if step.startswith('PT') and step.endswith('H') else 1
        out, t = [], start
        while t <= end:
            out.append(t)
            t += dt.timedelta(hours=hours)
        return out
    return [utc(x) for x in text.split(',') if x.strip()]


def capabilities(fetch, layer):
    url = GEOMET + '?' + urllib.parse.urlencode({'service': 'WMS', 'version': '1.3.0', 'request': 'GetCapabilities', 'layer': layer})
    root = ET.fromstring(fetch(url))
    for el in root.iter():
        if el.tag.endswith('Layer'):
            name = next((c.text for c in el if c.tag.endswith('Name')), None)
            if name != layer:
                continue
            dims = {d.get('name'): d for d in el.iter() if d.tag.endswith('Dimension')}
            if 'time' not in dims:
                break
            ref = dims.get('reference_time')
            return parse_times(dims['time'].text), (ref.get('default') if ref is not None else None)
    raise ValueError(f'Couche {layer} absente de GeoMet')


def first_layer(fetch, names):
    errors = []
    for name in names:
        try:
            return name, *capabilities(fetch, name)
        except Exception as e:
            errors.append(f'{name}: {str(e)[:60]}')
    raise ValueError(' · '.join(errors))


def feature_value(fetch, layer, time, ref, lat, lon):
    d = 0.02
    q = {'service': 'WMS', 'version': '1.3.0', 'request': 'GetFeatureInfo', 'layers': layer, 'query_layers': layer,
         'crs': 'EPSG:4326', 'bbox': f'{lat-d},{lon-d},{lat+d},{lon+d}', 'width': 3, 'height': 3, 'i': 1, 'j': 1,
         'info_format': 'application/json', 'time': zulu(time)}
    if ref:
        q['dim_reference_time'] = ref
    j = fetch(GEOMET + '?' + urllib.parse.urlencode(q), True)
    feats = j.get('features') or []
    v = feats[0].get('properties', {}).get('value') if feats else None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def eccc_model(key, fetch, lat, lon, now):
    name, pr_names, tt_names, horizon = ECCC_MODELS[key]
    pr_layer, pr_times, ref = first_layer(fetch, pr_names)
    tt_layer, tt_times, _ = first_layer(fetch, tt_names)
    limit = now + dt.timedelta(hours=horizon)
    times = [t for t in pr_times if t <= limit and t >= now - dt.timedelta(hours=2)]
    tt_set = set(tt_times)
    with futures.ThreadPoolExecutor(max_workers=8) as pool:
        pr = dict(zip(times, pool.map(lambda t: feature_value(fetch, pr_layer, t, ref, lat, lon), times)))
        tts = [t for t in times if t in tt_set]
        tt = dict(zip(tts, pool.map(lambda t: feature_value(fetch, tt_layer, t, ref, lat, lon), tts)))
    hours = []
    for a, b in zip(times, times[1:]):
        if (b - a) != dt.timedelta(hours=1) or pr.get(a) is None or pr.get(b) is None:
            continue
        mm = max(0.0, round(pr[b] - pr[a], 2))  # PR est cumulée depuis le début du modèle.
        temp = tt.get(b, tt.get(a))
        hours.append({'time': zulu(a), 'precip_mm': mm, 'temp': temp, 'snow_cm': snow_from_precip(mm, temp)})
    if len(hours) < 6:
        raise ValueError(f'Série {key.upper()} trop courte ({len(hours)} h)')
    return {'issued_at': ref, 'layers': [pr_layer, tt_layer], 'hours': hours}


def met_model(met_result):
    rows = met_result.get('hourly', [])
    hours = []
    for a, b in zip(rows, rows[1:]):
        step = (utc(b['time']) - utc(a['time'])).total_seconds() / 3600
        if a.get('precip_mm') is None or step <= 0 or step > 6:
            continue
        per = a['precip_mm'] / step
        for k in range(int(step)):
            t = utc(a['time']) + dt.timedelta(hours=k)
            hours.append({'time': zulu(t), 'precip_mm': round(per, 2), 'temp': a['temp'],
                          'snow_cm': snow_from_precip(per, a['temp'])})
    if len(hours) < 6:
        raise ValueError('Série MET Norway indisponible')
    return {'issued_at': met_result.get('issued_at'), 'hours': hours[:HORIZON_H + 12]}


def ncss_csv(fetch, var, lat, lon, now, extra=None):
    q = {'var': var, 'latitude': lat, 'longitude': lon, 'time_start': zulu(now - dt.timedelta(hours=1)),
         'time_end': zulu(now + dt.timedelta(hours=HORIZON_H)), 'accept': 'csv', **(extra or {})}
    rows = list(csv.reader(io.StringIO(fetch(THREDDS + '?' + urllib.parse.urlencode(q)))))
    head = rows[0]
    col = next(i for i, h in enumerate(head) if h.startswith(var))
    unit = head[col]
    return {utc(r[0]): float(r[col]) for r in rows[1:] if len(r) > col and r[col] not in ('', 'NaN')}, unit


def gfs_model(fetch, lat, lon, now):
    errors = []
    for var in ('Precipitation_rate_surface', 'Precipitation_rate_surface_Mixed_intervals_Average'):
        try:
            rate, unit = ncss_csv(fetch, var, lat, lon, now)
            break
        except Exception as e:
            errors.append(f'{var}: {str(e)[:60]}')
    else:
        raise ValueError(' · '.join(errors))
    temp, tunit = ncss_csv(fetch, 'Temperature_height_above_ground', lat, lon, now, {'vertCoord': 2})
    hours = []
    for t in sorted(rate):
        if t not in temp:
            continue
        mm = max(0.0, rate[t] * 3600)  # kg m-2 s-1 -> mm/h
        c = temp[t] - 273.15 if 'K' in tunit or temp[t] > 150 else temp[t]
        hours.append({'time': zulu(t), 'precip_mm': round(mm, 2), 'temp': round(c, 1), 'snow_cm': snow_from_precip(mm, c)})
    # Au-delà de 120 h le pas devient 3 h : on garde seulement les heures consécutives.
    hours = [h for h, n in zip(hours, hours[1:] + [None]) if n and utc(n['time']) - utc(h['time']) == dt.timedelta(hours=1)]
    if len(hours) < 6:
        raise ValueError(f'Série GFS trop courte ({len(hours)} h)')
    return {'issued_at': None, 'units': [unit, tunit], 'hours': hours}


NOTE = 'cm estimés à partir des mm d’eau et de la température (rapport 10:1 près de 0 °C, plus léger au froid). Pas de fonte ni de tassement.'


def collect_models(fetch, met_result, lat, lon, now, previous=None):
    jobs = {
        'hrdps': lambda: eccc_model('hrdps', fetch, lat, lon, now),
        'rdps': lambda: eccc_model('rdps', fetch, lat, lon, now),
        'gfs': lambda: gfs_model(fetch, lat, lon, now),
        'met': lambda: met_model(met_result or {}),
    }
    names = {'hrdps': ECCC_MODELS['hrdps'][0], 'rdps': ECCC_MODELS['rdps'][0], 'gfs': 'GFS 0,25° · NOAA', 'met': 'MET Norway'}
    out = []
    with futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = {k: pool.submit(fn) for k, fn in jobs.items()}
        for k, job in results.items():
            try:
                r = job.result()
                out.append({'id': k, 'name': names[k], 'status': 'ok', 'fetched_at': zulu(now), 'note': NOTE, **r})
            except Exception as e:
                out.append({'id': k, 'name': names[k], 'status': 'unavailable', 'fetched_at': zulu(now), 'hours': [], 'error': str(e)[:200]})
    return out
