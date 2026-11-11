"""Lecture de champs GRIB2 au point de Saint-Prosper, sans télécharger les fichiers entiers.

Chaque fichier de prévision (ECMWF, NOAA GFS) est accompagné d'un index qui donne la
position de chaque champ. On ne télécharge que les octets des champs utiles (requête Range),
puis eccodes lit la valeur au point de grille le plus proche.
"""
import json
import threading
import time
import urllib.error
import urllib.request

_LOCK = threading.Lock()  # eccodes n'est pas sûr entre fils d'exécution
threading.stack_size(16 * 1024 * 1024)  # l'analyseur d'eccodes est récursif : pile plus grande dans les fils


def warmup():
    """Charge les définitions eccodes dans le fil principal avant les téléchargements parallèles."""
    import eccodes
    with _LOCK:
        eccodes.codes_release(eccodes.codes_grib_new_from_samples('GRIB2'))
UA = 'DeneigementSaintProsper/1.0 (https://github.com/mdulac86/Deneigement)'


def get(url, byte_range=None, tries=6):
    headers = {'User-Agent': UA}
    if byte_range:
        headers['Range'] = f'bytes={byte_range[0]}-{byte_range[1]}'
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(url) from e
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
        time.sleep(min(30, 2 ** i))  # SlowDown d'Amazon S3 : on ralentit.
    raise RuntimeError(url)


def ecmwf_index(url):
    """Index JSON-lignes ECMWF -> liste de dict (param, step, number, _offset, _length)."""
    return [json.loads(l) for l in get(url).decode().splitlines() if l.strip()]


def ncep_index(url, size=None):
    """Index texte NOAA (.idx) -> liste de dict (var, level, desc, _offset, _length)."""
    rows = []
    for line in get(url).decode().splitlines():
        p = line.split(':')
        if len(p) >= 6:
            rows.append({'var': p[3], 'level': p[4], 'desc': p[5], '_offset': int(p[1])})
    for a, b in zip(rows, rows[1:]):
        a['_length'] = b['_offset'] - a['_offset']
    if rows:
        rows[-1]['_length'] = (size - rows[-1]['_offset']) if size else 5_000_000
    return rows


def point_value(data, lat, lon):
    import eccodes  # importé ici : seul le robot GitHub en a besoin.
    with _LOCK:
        gid = eccodes.codes_new_from_message(data)
        try:
            return float(eccodes.codes_grib_find_nearest(gid, lat, lon)[0].value)
        finally:
            eccodes.codes_release(gid)


def field(url, entry, lat, lon):
    data = get(url, (entry['_offset'], entry['_offset'] + entry['_length'] - 1))
    return point_value(data, lat, lon)
