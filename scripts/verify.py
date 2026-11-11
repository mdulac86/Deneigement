"""Tableau de fiabilité : qui avait vu juste à Saint-Prosper ?

Compare la neige prévue LA VEILLE pour chaque jour à la neige mesurée par Climat Québec.
- Base historique : data/verification/historique-*.json (scripts/history.py).
- Suivi en direct : archives du robot (data/archive), dernière collecte avant minuit la veille.

Indicateurs par source :
- écart moyen (cm) sur les jours où il a neigé ou où de la neige était prévue;
- biais (cm) : + = prévoit trop, - = pas assez;
- tempêtes de 5 cm et plus : détectées, manquées, fausses alertes.
Les jours sans observation valide ne comptent pas.
"""
import datetime as dt
import json
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TZ = ZoneInfo('America/Toronto')
SEUIL = 5
SNOWY = 1.0

LIVE_NAMES = {
    'mm': 'MétéoMédia', 'wu': 'Weather Underground', 'hrdps': 'HRDPS (canadien 2,5 km)', 'rdps': 'RDPS (canadien 10 km)',
    'gfs-live': 'NOAA GFS (américain)', 'met': 'MET Norway', 'ifs-live': 'ECMWF IFS (européen)', 'consensus': 'Consensus du plan (médiane)',
}


def load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def observations():
    obs = {}
    for p in sorted(DATA.glob('season-*.json')):
        for r in load(p, {}).get('records', []):
            obs[r['date']] = r.get('snow_cm')
    return obs


def history_pairs():
    pairs, names = {}, {}
    for p in sorted((DATA / 'verification').glob('historique-*.json')):
        h = load(p, {})
        names.update(h.get('sources', {}))
        for day, row in h.get('days', {}).items():
            o = (row.get('obs') or {}).get('snow_cm')
            for k, fc in row.get('fc', {}).items():
                if o is not None and fc.get('snow_cm') is not None:
                    pairs.setdefault(k, {})[day] = (fc['snow_cm'], o)
    return pairs, names


def snapshot_for(day):
    """Dernière archive du robot avant minuit (heure locale) la veille du jour visé."""
    limit = dt.datetime.combine(day, dt.time(0), TZ).astimezone(dt.timezone.utc)
    best = None
    for d in (day - dt.timedelta(days=1), day):
        folder = DATA / 'archive' / d.isoformat()
        for f in sorted(folder.glob('*.json')) if folder.exists() else []:
            t = dt.datetime.combine(d, dt.time(int(f.stem)), dt.timezone.utc)
            if t < limit and (best is None or t > best[0]):
                best = (t, f)
    return load(best[1], None) if best else None


def day_hours_sum(hours, day, key='snow_cm'):
    vals = []
    for h in hours or []:
        t = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(TZ)
        if t.date() == day and h.get(key) is not None:
            vals.append(h[key])
    return round(sum(vals), 1) if len(vals) >= 20 else None


def live_forecasts(day):
    snap = snapshot_for(day)
    if not snap:
        return {}
    out = {}
    for s in snap.get('sources', []):
        if s.get('status') != 'ok' or s['id'] not in ('mm', 'wu'):
            continue
        d = next((x for x in s.get('days', []) if x['date'] == str(day)), None)
        if d and d.get('snow_cm') is not None:
            out[s['id']] = round(sum(d['snow_cm']) / 2, 1)
    for m in snap.get('models', []):
        if m.get('status') == 'ok' and m['id'] != 'mm':
            v = day_hours_sum(m.get('hours'), day)
            if v is not None:
                out[{'gfs': 'gfs-live', 'ifs': 'ifs-live'}.get(m['id'], m['id'])] = v
    v = day_hours_sum(snap.get('hourly_snow'), day)
    if v is not None:
        out['consensus'] = v
    return out


def live_pairs(obs):
    pairs = {}
    for day_s, o in obs.items():
        if o is None:
            continue
        for k, v in live_forecasts(dt.date.fromisoformat(day_s)).items():
            pairs.setdefault(k, {})[day_s] = (v, o)
    return pairs


def score(pairs):
    snowy = [(f, o) for f, o in pairs.values() if f >= SNOWY or o >= SNOWY]
    hits = sum(1 for f, o in pairs.values() if f >= SEUIL and o >= SEUIL)
    miss = sum(1 for f, o in pairs.values() if f < SEUIL and o >= SEUIL)
    false = sum(1 for f, o in pairs.values() if f >= SEUIL and o < SEUIL)
    return {
        'jours': len(pairs), 'jours_neige': len(snowy),
        'ecart_moyen_cm': round(statistics.mean(abs(f - o) for f, o in snowy), 1) if snowy else None,
        'biais_cm': round(statistics.mean(f - o for f, o in snowy), 1) if snowy else None,
        'total_prevu_cm': round(sum(f for f, _ in pairs.values()), 1), 'total_mesure_cm': round(sum(o for _, o in pairs.values()), 1),
        'tempetes': {'detectees': hits, 'manquees': miss, 'fausses_alertes': false},
        'periode': [min(pairs), max(pairs)] if pairs else None,
    }


def ranked(pairs, names):
    rows = [{'id': k, 'nom': names.get(k, k), **score(v)} for k, v in pairs.items() if v]
    return sorted(rows, key=lambda r: (r['ecart_moyen_cm'] is None, r['ecart_moyen_cm'] or 0))


def main():
    hist, names = history_pairs()
    obs = observations()
    live = live_pairs(obs)
    result = {
        'genere': dt.datetime.now(dt.timezone.utc).isoformat(),
        'seuil_cm': SEUIL,
        'methode': 'Prévision de la veille comparée à la neige mesurée (Climat Québec 7027660). Écart moyen calculé sur les jours avec au moins 1 cm prévu ou mesuré.',
        'historique': ranked(hist, names),
        'en_direct': ranked(live, LIVE_NAMES),
    }
    (DATA / 'verification').mkdir(parents=True, exist_ok=True)
    (DATA / 'verification' / 'scores.json').write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for r in result['historique']:
        print(r['nom'], r['ecart_moyen_cm'], r['biais_cm'], r['tempetes'])


if __name__ == '__main__':
    main()
