"""Neige au sol en temps réel : stations automatiques d'Environnement Canada (SWOB) autour de Saint-Prosper.

Les capteurs à ultrasons mesurent l'épaisseur de neige au sol chaque heure : on voit les
accumulations, le tassement et la fonte. Une valeur négative ou absente reste None.
La station de Saint-Prosper (Climat Québec 7027660) publie aussi la neige au sol, une fois par
jour et avec un délai : elle est déjà dans les relevés de la saison.
"""
import datetime as dt
import math
import urllib.parse

API = 'https://api.weather.gc.ca/collections/swob-realtime/items'
HOME = (46.214, -70.486)
STATIONS = [
    ('7026930', 'Saint-Camille-de-Lellis', 46.495, -70.207),
    ('7028442', 'Thetford Mines', 46.049, -71.266),
    ('7023681', 'Nantes (Lac-Mégantic)', 45.606, -70.933),
]
HOURS = 72


def km(lat, lon):
    r = 6371
    p1, p2 = math.radians(HOME[0]), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lon - HOME[1])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def value(p, *keys):
    for k in keys:
        v = p.get(k)
        if isinstance(v, (int, float)) and v >= 0:
            return float(v)
    return None


def hourly(features):
    """Une mesure par heure : la plus proche de l'heure pile."""
    best = {}
    for f in features:
        p = f.get('properties', {})
        t = p.get('date_tm-value')
        if not t:
            continue
        when = dt.datetime.fromisoformat(t.replace('Z', '+00:00'))
        hour = when.replace(minute=0, second=0, microsecond=0)
        gap = abs((when - hour).total_seconds())
        if hour not in best or gap < best[hour][0]:
            temp = p.get('air_temp')
            best[hour] = (gap, {'time': hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
                                'depth_cm': value(p, 'avg_snw_dpth_pst5mts', 'snw_dpth'),
                                'temp': temp if isinstance(temp, (int, float)) else None,
                                'gust': value(p, 'max_wnd_spd_10m_pst1hr', 'max_wnd_spd_10m_pst10mts')})
    return [best[h][1] for h in sorted(best)]


def change(series, hours=24):
    pts = [s for s in series if s['depth_cm'] is not None]
    if len(pts) < 2:
        return None
    last = pts[-1]
    t_last = dt.datetime.fromisoformat(last['time'].replace('Z', '+00:00'))
    ref = min(pts, key=lambda s: abs((t_last - dt.datetime.fromisoformat(s['time'].replace('Z', '+00:00'))).total_seconds() - hours * 3600))
    return round(last['depth_cm'] - ref['depth_cm'], 1)


def station(fetch, clim_id, name, lat, lon, now):
    since = (now - dt.timedelta(hours=HOURS)).strftime('%Y-%m-%dT%H:00:00Z')
    q = {'f': 'json', 'clim_id-value': clim_id, 'datetime': f'{since}/..', 'limit': 5000}
    series = hourly(fetch(API + '?' + urllib.parse.urlencode(q), True).get('features', []))
    pts = [s for s in series if s['depth_cm'] is not None]
    if not series:
        raise ValueError('Aucune observation récente')
    return {'id': clim_id, 'name': name, 'km': km(lat, lon), 'status': 'ok', 'series': series,
            'latest': pts[-1] if pts else None, 'change_24h': change(series),
            'temp': next((s['temp'] for s in reversed(series) if s['temp'] is not None), None),
            'gust_24h': max([x['gust'] for x in series[-24:] if x.get('gust') is not None], default=None)}


def collect(fetch, now):
    out = []
    for clim_id, name, lat, lon in STATIONS:
        try:
            out.append(station(fetch, clim_id, name, lat, lon, now))
        except Exception as e:
            out.append({'id': clim_id, 'name': name, 'km': km(lat, lon), 'status': 'unavailable', 'series': [], 'error': str(e)[:150]})
    return {'stations': out, 'note': 'Capteurs automatiques d’Environnement Canada (mesure horaire de l’épaisseur de neige au sol). '
            'Une baisse sans pluie = tassement; une baisse avec redoux ou pluie = fonte.'}


def daily_gusts(stations, tz, store):
    """Vent maximal (km/h) par jour local, toutes stations confondues, gardé pour la saison."""
    for st in stations:
        for h in st.get('series', []):
            if h.get('gust') is None:
                continue
            day = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(tz).date().isoformat()
            store[day] = max(store.get(day, 0), h['gust'])
    return dict(sorted(store.items())[-260:])
