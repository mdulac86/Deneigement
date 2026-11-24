"""Base historique : prévisions passées des modèles ouverts vs neige mesurée à Saint-Prosper.

Pour chaque jour D de la saison, on prend la prévision émise la veille (run de 00 h UTC du
jour D-1) pour la fenêtre 06 h UTC D -> 06 h UTC D+1 (1 h -> 1 h, heure normale de l'Est),
soit les échéances 30 h -> 54 h. C'est la prévision qu'on aurait eue en soirée pour planifier.

Sources archivées publiquement (Amazon Open Data) :
- ECMWF IFS 0,25° et AIFS (CC BY 4.0) : neige tombée (sf) et précipitations (tp) directes;
- NOAA GFS 0,25° : précipitations par tranche de 6 h + température -> cm estimés;
- NOAA NBM (cycle 00 h UTC de la veille) et HRRR (run 06 h UTC de la veille, échéances 24-48 h) :
  neige fournie par le modèle.
Observations : Climat Québec, station 7027660 (relevés quotidiens).

Les modèles canadiens (HRDPS, RDPS), MétéoMédia et Weather Underground
n'ont pas d'archive publique : ils sont évalués à partir des archives du robot (verify.py).

Usage : python scripts/history.py 2025-11-01 2026-04-30
"""
import concurrent.futures as futures
import datetime as dt
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grib  # noqa: E402
import noaa  # noqa: E402
from models import snow_from_precip  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'verification'
LAT, LON = 46.214, -70.486
ECMWF = 'https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com'
GFS = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
STEPS = (30, 54)


VERSION = {'ifs': 1, 'aifs': 2, 'gfs': 1, 'nbm': 1, 'hrrr': 1}


def ecmwf_day(day, model):
    run = (day - dt.timedelta(days=1)).strftime('%Y%m%d')
    vals = {}
    for step in STEPS:
        base = f'{ECMWF}/{run}/00z/{model}/0p25/oper/{run}000000-{step}h-oper-fc'
        idx = grib.ecmwf_index(base + '.index')
        for param in ('tp', 'sf', '2t'):
            entry = next((e for e in idx if e.get('param') == param), None)
            if entry is not None:
                v, u = grib.field(base + '.grib2', entry, LAT, LON, units=True)
                vals[(param, step)] = v if param == '2t' else grib.to_mm(v, u)
    if ('tp', 30) not in vals or ('tp', 54) not in vals:
        raise ValueError(f'tp absent ({model} {run})')
    tp = max(0.0, vals[('tp', 54)] - vals[('tp', 30)])
    if ('sf', 30) in vals and ('sf', 54) in vals:
        snow, how = max(0.0, vals[('sf', 54)] - vals[('sf', 30)]), 'neige du modèle'
    else:  # Anciennes données sans « sf » : estimation par la température comme les autres modèles.
        temps = [vals[('2t', s)] - 273.15 for s in STEPS if ('2t', s) in vals]
        snow, how = snow_from_precip(tp, sum(temps) / len(temps)) if temps else None, 'estimée (pluie + température)'
    return {'tp_mm': round(tp, 1), 'snow_cm': None if snow is None else round(snow, 1), 'calcul': how}  # 1 mm d'eau ≈ 1 cm (10:1)


def gfs_day(day):
    run = (day - dt.timedelta(days=1)).strftime('%Y%m%d')
    temps, buckets = {}, {}
    for step in range(30, 55, 6):
        base = f'{GFS}/gfs.{run}/00/atmos/gfs.t00z.pgrb2.0p25.f{step:03d}'
        idx = grib.ncep_index(base + '.idx')
        t = next(e for e in idx if e['var'] == 'TMP' and e['level'] == '2 m above ground')
        temps[step] = grib.field(base, t, LAT, LON) - 273.15
        if step > 30:
            a = next(e for e in idx if e['var'] == 'APCP' and e['desc'] == f'{step-6}-{step} hour acc fcst')
            buckets[step] = max(0.0, grib.field(base, a, LAT, LON))
    tp = sum(buckets.values())
    snow = sum(snow_from_precip(mm, (temps[s - 6] + temps[s]) / 2) for s, mm in buckets.items())
    return {'tp_mm': round(tp, 1), 'snow_cm': round(snow, 1), 'calcul': 'estimée (pluie + température)'}


def nbm_day(day):
    """NBM, cycle 00 h UTC de la veille : 4 tranches de 6 h (f030 -> f054), neige fournie (ASNOW, m)."""
    run = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(0), dt.timezone.utc)
    snow = tp = 0.0
    for f in (36, 42, 48, 54):
        url = noaa.nbm_url(run, f)
        rows = noaa.index(url)
        win = f'{f - 6}-{f} hour acc fcst'
        s, p = noaa.pick(rows, f'ASNOW:surface:{win}'), noaa.pick(rows, f'APCP:surface:{win}')
        if not s or not p:
            raise ValueError(f'tranche {win} absente')
        snow += max(0.0, noaa.to_cm(*grib.field(url, s, LAT, LON, units=True)))
        tp += max(0.0, grib.field(url, p, LAT, LON))
    return {'tp_mm': round(tp, 1), 'snow_cm': round(snow, 1), 'calcul': 'neige du modèle'}


def hrrr_day(day):
    """HRRR, run 06 h UTC de la veille : cumul 24 h -> 48 h = 06 h UTC J -> 06 h UTC J+1."""
    run = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(6), dt.timezone.utc)
    vals = {}
    for f, acc in ((24, '0-1 day acc fcst'), (48, '0-2 day acc fcst')):
        url = noaa.hrrr_url(run, f)
        rows = noaa.index(url)
        for var in ('ASNOW', 'APCP'):
            e = noaa.pick(rows, f'{var}:surface:{acc}')
            if not e:
                raise ValueError(f'{var} {acc} absent')
            v, u = grib.field(url, e, LAT, LON, units=True)
            vals[(var, f)] = noaa.to_cm(v, u) if var == 'ASNOW' else v
    snow = max(0.0, vals[('ASNOW', 48)] - vals[('ASNOW', 24)])
    tp = max(0.0, vals[('APCP', 48)] - vals[('APCP', 24)])
    return {'tp_mm': round(tp, 1), 'snow_cm': round(snow, 1), 'calcul': 'neige du modèle'}


SOURCES = {
    'ifs': ('ECMWF IFS (européen)', lambda d: ecmwf_day(d, 'ifs')),
    'aifs': ('ECMWF AIFS (européen, IA)', lambda d: ecmwf_day(d, 'aifs-single')),
    'gfs': ('NOAA GFS (américain)', gfs_day),
    'nbm': ('NOAA NBM (synthèse américaine)', nbm_day),
    'hrrr': ('NOAA HRRR (américain 3 km)', hrrr_day),
}


def observations(start, end):
    import collect  # parseur Climat Québec existant
    rows = {}
    months = sorted({(d.year, d.month) for d in (start + dt.timedelta(days=i) for i in range((end - start).days + 1))})
    for y, m in months:
        for r in collect.climat_month(y, m):
            rows[r['date']] = {'snow_cm': r['snow_cm'], 'rain_mm': r['rain_mm']}
    return rows


def stale(fc):
    """Sources à (re)calculer pour un jour : absentes, en erreur ou calculées par une ancienne version."""
    return [k for k in SOURCES if k not in fc or 'error' in fc[k] or fc[k].get('v', 1) != VERSION[k]]


def one_day(day, previous=None):
    out = dict(previous or {})
    for key in stale(out):
        try:
            out[key] = {**SOURCES[key][1](day), 'v': VERSION[key]}
        except Exception as e:
            out[key] = {'error': str(e)[:120]}
    return str(day), out


def main(start, end):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f'historique-{start:%Y%m%d}-{end:%Y%m%d}.json'
    done = json.loads(path.read_text(encoding='utf-8'))['days'] if path.exists() else {}
    grib.warmup()
    obs = observations(start, end)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    todo = [d for d in days if str(d) not in done or stale(done[str(d)]['fc'])]
    print(f'{len(todo)} jours à calculer sur {len(days)}', flush=True)
    with futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = pool.map(lambda d: one_day(d, done.get(str(d), {}).get('fc')), todo)
        for i, (day, fc) in enumerate(jobs):
            done[day] = {'obs': obs.get(day), 'fc': fc}
            if i % 10 == 0:
                print(day, json.dumps(fc), flush=True)
    for d in days:
        if str(d) in done:
            done[str(d)]['obs'] = obs.get(str(d))
    result = {'start': str(start), 'end': str(end),
              'window': 'Prévision de la veille (run 00 h UTC J-1), échéances 30-54 h : 06 h UTC J -> 06 h UTC J+1.',
              'sources': {k: v[0] for k, v in SOURCES.items()},
              'observations': 'Climat Québec, station automatique 7027660 Saint-Prosper (neige indicative calculée selon la température).',
              'days': dict(sorted(done.items()))}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('écrit', path)


if __name__ == '__main__':
    a = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.date(2025, 11, 1)
    b = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.date(2026, 4, 30)
    main(a, b)
