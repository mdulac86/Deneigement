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
MIN_VERSION = {'aifs': 2}  # AIFS v1 : unités mal converties

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
    pairs, precip, names = {}, {}, {}
    for p in sorted((DATA / 'verification').glob('historique-*.json')):
        h = load(p, {})
        names.update(h.get('sources', {}))
        for day, row in h.get('days', {}).items():
            obs = row.get('obs') or {}
            o = obs.get('snow_cm')
            water = None if o is None or obs.get('rain_mm') is None else obs['rain_mm'] + o  # neige à 10:1
            for k, fc in row.get('fc', {}).items():
                if fc.get('v', 1) < MIN_VERSION.get(k, 1):
                    continue  # calcul d'une version corrigée depuis
                if o is not None and fc.get('snow_cm') is not None:
                    pairs.setdefault(k, {})[day] = (fc['snow_cm'], o)
                if water is not None and fc.get('tp_mm') is not None:
                    precip.setdefault(k, {})[day] = (fc['tp_mm'], water)
    return pairs, precip, names


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


def episodes(pairs):
    """Épisodes de neige observés : jours consécutifs avec neige mesurée, élargis d'un jour de chaque
    côté. Comparer les totaux par épisode évite de pénaliser une tempête qui chevauche minuit."""
    days = sorted(pairs)
    snowy = [d for d in days if pairs[d][1] >= SNOWY]
    groups, cur = [], []
    for d in snowy:
        if cur and (dt.date.fromisoformat(d) - dt.date.fromisoformat(cur[-1])).days > 2:
            groups.append(cur)
            cur = []
        cur.append(d)
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        a = dt.date.fromisoformat(g[0]) - dt.timedelta(days=1)
        b = dt.date.fromisoformat(g[-1]) + dt.timedelta(days=1)
        span = [d for d in days if a <= dt.date.fromisoformat(d) <= b]
        out.append((span, sum(pairs[d][0] for d in span), sum(pairs[d][1] for d in span)))
    return out


def score(pairs, precip=None):
    eps = episodes(pairs)
    covered = {d for span, _, _ in eps for d in span}
    big = [(f, o) for _, f, o in eps if o >= SEUIL]
    hits = sum(1 for f, _ in big if f >= SEUIL)
    false = 0
    for d, (f, o) in sorted(pairs.items()):
        if f >= SEUIL and not any(d in span and ot >= SEUIL / 2 for span, _, ot in eps):
            false += 1
    daily = [(f, o) for f, o in pairs.values() if f >= SNOWY or o >= SNOWY]
    p = [(f, o) for f, o in (precip or {}).values() if f >= 1 or o >= 1]
    return {
        'jours': len(pairs), 'episodes': len(eps),
        'ecart_moyen_cm': round(statistics.mean(abs(f - o) for _, f, o in eps), 1) if eps else None,
        'biais_cm': round(statistics.mean(f - o for _, f, o in eps), 1) if eps else None,
        'ecart_jour_cm': round(statistics.mean(abs(f - o) for f, o in daily), 1) if daily else None,
        'ecart_precip_mm': round(statistics.mean(abs(f - o) for f, o in p), 1) if p else None,
        'total_prevu_cm': round(sum(f for f, _ in pairs.values()), 1), 'total_mesure_cm': round(sum(o for _, o in pairs.values()), 1),
        'tempetes': {'detectees': hits, 'manquees': len(big) - hits, 'fausses_alertes': false},
        'periode': [min(pairs), max(pairs)] if pairs else None,
    }


def ranked(pairs, names, precip=None):
    rows = [{'id': k, 'nom': names.get(k, k), **score(v, (precip or {}).get(k))} for k, v in pairs.items() if v]
    return sorted(rows, key=lambda r: (r['ecart_moyen_cm'] is None, r['ecart_moyen_cm'] or 0))


def main():
    hist, hist_precip, names = history_pairs()
    obs = observations()
    live = live_pairs(obs)
    result = {
        'genere': dt.datetime.now(dt.timezone.utc).isoformat(),
        'seuil_cm': SEUIL,
        'methode': 'Prévision de la veille comparée à la neige mesurée par Climat Québec (station 7027660). Écart moyen = écart sur le total de chaque épisode de neige (une tempête qui chevauche minuit compte une seule fois). La neige de la station est calculée à partir des précipitations et de la température : les précipitations (mm d’eau) sont la mesure la plus sûre.',
        'historique': ranked(hist, names, hist_precip),
        'en_direct': ranked(live, LIVE_NAMES),
    }
    (DATA / 'verification').mkdir(parents=True, exist_ok=True)
    (DATA / 'verification' / 'scores.json').write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for r in result['historique']:
        print(r['nom'], r['ecart_moyen_cm'], r['biais_cm'], r['ecart_precip_mm'], r['tempetes'])


if __name__ == '__main__':
    main()
