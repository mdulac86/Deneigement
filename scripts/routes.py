"""Routes autour de Saint-Prosper : données ouvertes du ministère des Transports (MTQ, Québec 511).

- État des routes en hiver (chaussée, visibilité, lames de neige), mis à jour par les
  patrouilleurs du MTQ, segment par segment.
- Avertissements routiers en cours (fermetures, entraves).
- Caméras de circulation : courte vidéo récente servie par Québec 511.
- Période de dégel de la zone (restrictions de charge des camions au printemps) et chantiers
  routiers, en premier ceux qui limitent la charge ou les dimensions (transport de machinerie).

Service WFS du MTQ, licence CC BY 4.0 (Données Québec). Fonctions pures sauf get_json();
testées dans tests/test_routes.py.
"""
import math
import urllib.parse

WFS = 'https://ws.mapserver.transports.gouv.qc.ca/swtq'
RAYON_KM = 45
SOURCE = 'https://www.quebec511.info/fr/'
CAMERA_VIDEO = 'https://www.quebec511.info/Carte/Fenetres/camera.ashx?id={id}&format=mp4'


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def points(geom):
    """Tous les sommets (lon, lat) d'une géométrie GeoJSON."""
    if not geom:
        return []
    c, t = geom.get('coordinates'), geom.get('type')
    if t == 'Point':
        return [c]
    if t in ('LineString', 'MultiPoint'):
        return c
    if t in ('MultiLineString', 'Polygon'):
        return [p for part in c for p in part]
    if t == 'MultiPolygon':
        return [p for poly in c for part in poly for p in part]
    return []


def distance(geom, lat, lon):
    pts = points(geom)
    return round(min(km(lat, lon, p[1], p[0]) for p in pts), 1) if pts else None


def query(layer, lat, lon, rayon=RAYON_KM):
    dlat, dlon = rayon / 111, rayon / (111 * math.cos(math.radians(lat)))
    return WFS + '?' + urllib.parse.urlencode({
        'service': 'wfs', 'version': '2.0.0', 'request': 'getfeature', 'typename': 'ms:' + layer,
        'outputformat': 'geojson', 'srsName': 'EPSG:4326',
        'bbox': f'{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon},urn:ogc:def:crs:EPSG::4326'})


def features(get_json, layer, lat, lon, rayon=RAYON_KM):
    out = []
    for f in get_json(query(layer, lat, lon, rayon)).get('features', []):
        d = distance(f.get('geometry'), lat, lon)
        if d is not None and d <= rayon:
            out.append((d, f.get('properties') or {}))
    return sorted(out, key=lambda x: x[0])


def oui(v):
    return str(v or '').strip().upper() in ('O', 'OUI', 'Y', 'TRUE', '1')


def gravite(chaussee, visibilite, lames):
    """0 = dégagée, 1 = à surveiller (mouillée, partiellement couverte), 2 = enneigée, 3 = glacée.
    Lu dans le libellé du MTQ (« Dégagée et sèche », « Partiellement enneigée », « Glacée »…)."""
    t = str(chaussee or '').lower()
    partiel = 'partiel' in t
    if 'glac' in t or 'vergla' in t:
        level = 2 if partiel else 3
    elif 'enneig' in t or 'neige' in t:
        level = 1 if partiel else 2
    elif partiel or any(w in t for w in ('mouill', 'humide', 'slush', 'gadoue')):
        level = 1
    else:
        level = 0
    v = str(visibilite or '').lower()
    if 'réduite' in v or 'reduite' in v or 'nulle' in v or 'faible' in v:
        level = max(level, 2)
    if lames:
        level = max(level, 2)
    return level


def segments(rows):
    out = []
    for d, p in rows:
        lames = oui(p.get('IndicateurPresenceLamesNeige'))
        out.append({'km': d, 'route': p.get('NomRoute') or ('route ' + str(p.get('NumeroRoute') or '')),
                    'de': p.get('LocalisationDebutFR'), 'a': p.get('LocalisationFinFR'),
                    'chaussee': p.get('DescriptionEtatChausseeFR'), 'code': p.get('CodeEtatChaussee'),
                    'visibilite': p.get('DescriptionVisibiliteFR'), 'lames_neige': lames,
                    'depuis': p.get('EnVigueurDepuis'),
                    'gravite': gravite(p.get('DescriptionEtatChausseeFR'), p.get('DescriptionVisibiliteFR'), lames)})
    return out


def evenements(rows):
    return [{'km': d, 'route': p.get('numeroRoute'), 'lieu': p.get('localisation'), 'municipalite': p.get('municipalite'),
             'direction': p.get('direction'), 'entrave': p.get('entrave'), 'cause': p.get('cause'),
             'duree': p.get('duree'), 'depuis': p.get('enVigueurDepuis')} for d, p in rows]


def cameras(rows, limit=8):
    out = []
    for d, p in rows[:limit]:
        cid = str(p.get('IDEcamera') or '').strip()
        if not cid.isdigit():
            continue
        out.append({'km': d, 'id': cid, 'nom': p.get('DescriptionLocalisationFr'), 'route': p.get('NumeroRoute'),
                    'video': CAMERA_VIDEO.format(id=cid), 'page': p.get('URL_FLUX_DONNEE')})
    return out


def degel(get_json, lat, lon):
    """Période de dégel (restrictions de charge des camions) de la zone du MTQ qui contient Saint-Prosper."""
    feats = get_json(query('zone_degel', lat, lon, rayon=1)).get('features', [])
    if not feats:
        return None
    p = feats[0].get('properties') or {}
    day = lambda s: str(s or '').strip()[:10] or None
    return {'zone': p.get('zone'), 'partie': p.get('nom_partie_zone'), 'debut': day(p.get('dat_debut_zone')),
            'fin': day(p.get('dat_fin_zone')), 'source': 'https://www.transports.gouv.qc.ca/fr/camionnage/periode-degel/'}


def travaux(rows, limit=10):
    """Chantiers routiers en cours ou prochains, en premier ceux qui limitent la charge ou les dimensions."""
    out = []
    for d, p in rows:
        out.append({'km': d, 'route': p.get('routeAutoroute') or None, 'travaux': p.get('identificationDesTravaux'),
                    'lieu': p.get('localisation'), 'entrave': p.get('entrave'),
                    'charge': (p.get('entravesLieesAuxChargesEtDimensions') or '').strip() or None,
                    'debut': str(p.get('debut') or '').replace('/', '-')[:16], 'fin': str(p.get('fin') or '').replace('/', '-')[:16]})
    return sorted(out, key=lambda t: (t['charge'] is None, t['km']))[:limit]


def resume(segs):
    """Pire état parmi les segments les plus proches (≤ 25 km)."""
    proches = [s for s in segs if s['km'] <= 25] or segs[:4]
    if not proches:
        return None
    pire = max(proches, key=lambda s: s['gravite'])
    return {'gravite': pire['gravite'], 'texte': f"{pire['chaussee'] or 'État inconnu'} · {pire['route']}"}


def collect(get_json, lat, lon, now_iso, previous=None):
    errors, out = [], {'fetched_at': now_iso, 'rayon_km': RAYON_KM, 'source': SOURCE,
                       'note': 'Données ouvertes du MTQ (Québec 511, CC BY 4.0). État des routes noté par les patrouilleurs; '
                               'vidéos des caméras servies par Québec 511.'}
    for key, layer, fn in (('segments', 'conditions_routieres', segments), ('evenements', 'evenements', evenements),
                           ('cameras', 'infos_cameras', cameras), ('travaux', 'chantiers_mtmdet', travaux)):
        try:
            out[key] = fn(features(get_json, layer, lat, lon))
        except Exception as e:
            errors.append(f'{layer} : {str(e)[:80]}')
            out[key] = (previous or {}).get(key, [])
    try:
        out['degel'] = degel(get_json, lat, lon)
    except Exception as e:
        errors.append(f'zone_degel : {str(e)[:80]}')
        out['degel'] = (previous or {}).get('degel')
    out['resume'] = resume(out['segments'])
    out['status'] = 'ok' if not errors else 'partial' if len(errors) < 5 else 'unavailable'
    if errors:
        out['errors'] = errors
    return out

