"""Gel dans le sol : profondeur de gel mesurée par le ministère des Transports (MTQ).

Station météoroutière de Saint-Georges (14 km de Saint-Prosper) : une sonde de 3 m sous la
chaussée mesure la température du sol; le MTQ publie chaque jour la profondeur de gel et de
dégel (données ouvertes, CC BY 4.0, environ 2 jours de décalage, du 1er nov. au 30 juin).
La chaussée est déneigée : le gel y descend plus creux que sous la neige d'un terrain.

Projection sur 10 jours : profondeur ≈ 0,053 × √(indice de gel), calée sur Saint-Georges
2014-2026 et les températures de Saint-Prosper (écart moyen ≈ 10 cm).
Fonctions pures sauf fetch(); testées dans tests/test_frost.py.
"""
import csv
import datetime as dt
import io
import math
import statistics
import urllib.parse

WFS = 'https://ws.mapserver.transports.gouv.qc.ca/swtq'
STATIONS = [('52', 'Saint-Georges', 14), ('57', 'Thetford Mines', 52)]
K = 0.053  # m par √(degré-jour)
SOURCE = 'https://www.donneesquebec.ca/recherche/fr/dataset/station-meteoroutiere'


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fetch_station(get_text, station_id):
    flt = ('<Filter xmlns="http://www.opengis.net/fes/2.0"><PropertyIsEqualTo>'
           f'<ValueReference>station_id</ValueReference><Literal>{station_id}</Literal>'
           '</PropertyIsEqualTo></Filter>')
    q = {'service': 'wfs', 'version': '2.0.0', 'request': 'getfeature',
         'typename': 'ms:histo_stations_meteoroutieres_tous', 'outputformat': 'csv', 'filter': flt}
    rows = {}
    for r in csv.DictReader(io.StringIO(get_text(WFS + '?' + urllib.parse.urlencode(q)).lstrip('﻿'))):
        g = num(r.get('prof_gel'))
        if g is not None and r.get('date_texte'):
            rows[r['date_texte']] = {'gel_m': g, 'degel_m': num(r.get('prof_degel'))}
    if not rows:
        raise ValueError('aucune mesure')
    return dict(sorted(rows.items()))


def season_of(day):
    return day.year if day.month >= 9 else day.year - 1


def normals(rows, day):
    """Médiane et maximum des hivers passés à la même date (même jour de l'année)."""
    vals, peaks = [], []
    for y in sorted({season_of(dt.date.fromisoformat(d)) for d in rows}):
        if y >= season_of(day):
            continue
        try:
            same = day.replace(year=y if day.month >= 9 else y + 1)
        except ValueError:  # 29 février
            same = day.replace(year=y if day.month >= 9 else y + 1, day=28)
        v = rows.get(str(same))
        if v:
            vals.append(v['gel_m'])
        season = [r['gel_m'] for d, r in rows.items() if season_of(dt.date.fromisoformat(d)) == y]
        if season:
            peaks.append(max(season))
    return {'normale_m': round(statistics.median(vals), 2) if vals else None,
            'max_moyen_m': round(statistics.mean(peaks), 2) if peaks else None,
            'hivers': len(peaks)}


def project(gel_m, days):
    """days : [{'date', 'high_mean', 'low_mean'}] après la dernière mesure.
    Le froid fait descendre le gel; le redoux le fait surtout fondre par le haut (profondeur gardée)."""
    fi = (gel_m / K) ** 2 if gel_m else 0.0
    out, deepest = [], gel_m or 0.0
    for d in days:
        hi, lo = d.get('high_mean'), d.get('low_mean')
        if hi is None or lo is None:
            continue
        t = (hi + lo) / 2
        fi = max(0.0, fi - t) if t < 0 else max(0.0, fi - 0.5 * t)
        deepest = max(deepest, K * math.sqrt(fi))
        out.append({'date': d['date'], 'gel_m': round(deepest, 2), 'degel_haut': t > 0 and deepest > 0})
    return out


def collect(get_text, today, consensus, previous=None):
    errs = []
    for sid, name, km in STATIONS:
        try:
            rows = fetch_station(get_text, sid)
            break
        except Exception as e:
            errs.append(f'{name} : {str(e)[:80]}')
    else:
        if previous:
            return {**previous, 'status': 'stale', 'error': '; '.join(errs)}
        return {'status': 'unavailable', 'error': '; '.join(errs)}
    last_day = max(rows)
    last = rows[last_day]
    season = [{'date': d, **r} for d, r in rows.items() if season_of(dt.date.fromisoformat(d)) == season_of(today)]
    prev_season = [r['gel_m'] for d, r in rows.items() if season_of(dt.date.fromisoformat(d)) == season_of(today) - 1]
    ahead = [d for d in consensus or [] if d['date'] > last_day]
    return {'status': 'ok', 'station': name, 'km': km, 'date': last_day, 'gel_m': last['gel_m'], 'degel_m': last['degel_m'],
            'saison': season[-200:], 'hiver_passe_max_m': max(prev_season) if prev_season else None,
            **normals(rows, dt.date.fromisoformat(last_day)), 'projection': project(last['gel_m'], ahead[:10]),
            'source': SOURCE,
            'note': 'Profondeur de gel sous la chaussée déneigée (sonde du MTQ, ≈ 2 jours de décalage). '
                    'Sous un terrain enneigé, le gel est en général moins profond.'}
