"""Plan d'épandage (sel + calcium ou abrasif) : pluie verglaçante, ou pluie / fonte suivie d'un regel.

Règles (config/epandage.json) :
- verglas ou grésil confirmé (Environnement Canada, 2 sources ou source mesurée fiable) : épandage au
  début de l'épisode, ou prêt pour 7 h 45 s'il arrive la nuit;
- pluie (1 mm et plus) ou fonte (4 h à +1 °C et plus avec de la neige au sol), puis retour sous 0 °C :
  épandage au regel, ou prêt pour 7 h 45 si le regel arrive la nuit;
- produit : sel + calcium jusqu'à -18 °C, abrasif plus froid; abrasif en plus après beaucoup d'eau.

Séries horaires : médianes des modèles pondérées par leur fiabilité mesurée (pluie : confiance_pluie);
une heure compte seulement si au moins 2 modèles la couvrent. Fonctions pures, testées dans tests/test_epandage.py.
"""
import datetime as dt
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'epandage.json'
HOUR = dt.timedelta(hours=1)


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def hm(text):
    h, m = text.split(':')
    return dt.time(int(h), int(m))


def wmedian(pairs):
    pairs = sorted((v, w) for v, w in pairs if v is not None and w > 0)
    tot = sum(w for _, w in pairs)
    c = 0.0
    for v, w in pairs:
        c += w
        if c >= tot / 2 - 1e-9:
            return v
    return None


def hourly(models, tz, now, horizon_h):
    """Heures locales : température, pluie liquide (mm), neige (cm), nombre de modèles."""
    end = now + dt.timedelta(hours=horizon_h)
    by = {}
    for m in models:
        if m.get('status') != 'ok':
            continue
        wp = (m.get('confiance_pluie') or {}).get('poids', 1.0)
        for h in m.get('hours') or []:
            t = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(tz)
            if t + HOUR <= now or t >= end:
                continue
            e = by.setdefault(t, {'temp': [], 'rain': [], 'snow': []})
            if h.get('temp') is not None:
                e['temp'].append((h['temp'], 1.0))
            if h.get('precip_mm') is not None:
                e['rain'].append((0.0 if (h.get('snow_cm') or 0) > 0 else h['precip_mm'], wp))
            if h.get('snow_cm') is not None:
                e['snow'].append((h['snow_cm'], 1.0))
    out = []
    for t in sorted(by):
        e = by[t]
        if len(e['temp']) < 2:
            continue
        out.append({'time': t, 'temp': wmedian(e['temp']), 'rain': wmedian(e['rain']) or 0.0,
                    'snow': wmedian(e['snow']) or 0.0, 'n': len(e['temp'])})
    return out


def ceil30(t):
    t = t.replace(second=0, microsecond=0)
    return t if t.minute in (0, 30) else t + dt.timedelta(minutes=30 - t.minute % 30)


def floor30(t):
    return t.replace(minute=t.minute - t.minute % 30, second=0, microsecond=0)


def schedule(t, cfg):
    """Heure d'épandage pour une glace qui se forme à t : la nuit (20 h - 7 h 45), prêt pour 7 h 45; le jour, à t."""
    dl_t, night = hm(cfg['echeance']), hm(cfg['debut_nuit'])
    if t.time() >= night:
        day = t.date() + dt.timedelta(days=1)
    elif t.time() <= dl_t:
        day = t.date()
    else:
        return ceil30(t), None
    deadline = dt.datetime.combine(day, dl_t, t.tzinfo)
    return max(floor30(deadline - dt.timedelta(hours=cfg['duree_h'])), floor30(t)), deadline


def product(tmin, water_mm, cfg):
    if tmin is not None and tmin < cfg['limite_sel_calcium_c']:
        return 'Abrasif', f'trop froid pour le sel + calcium (≈ {round(tmin):g} °C)'
    if water_mm >= cfg['beaucoup_eau_mm']:
        return f'{cfg["produit"]} + abrasif', f'beaucoup d’eau (≈ {round(water_mm):g} mm) : glace épaisse au regel'
    return cfg['produit'], None


def refreezes(hours, ground_cm, cfg):
    """Pluie ou fonte, puis retour sous le point de congélation -> (début du mouillé, regel, mm, heures de fonte)."""
    out, wet_start, mm, melt = [], None, 0.0, 0
    for i, h in enumerate(hours):
        # Pluie sous 0 °C = pluie verglaçante : elle passe par la confirmation du verglas (freezing), pas ici.
        wet = (h['rain'] >= 0.1 and h['temp'] > 0) or (ground_cm >= 2 and h['temp'] >= cfg['fonte_temp_c'])
        if wet:
            wet_start = wet_start or h['time']
            mm += h['rain'] if h['temp'] > 0 else 0
            melt += 1 if ground_cm >= 2 and h['temp'] >= cfg['fonte_temp_c'] else 0
            continue
        if wet_start and h['temp'] <= cfg['regel_temp_c']:
            if mm >= cfg['pluie_min_mm'] or melt >= cfg['fonte_min_h']:
                out.append((wet_start, h['time'], round(mm, 1), melt))
            wet_start, mm, melt = None, 0.0, 0
        elif wet_start and h['time'] - wet_start > dt.timedelta(hours=36):
            wet_start, mm, melt = None, 0.0, 0  # redoux qui dure : pas de regel proche
    return out


def freezing(hours, consensus):
    """Jours où le verglas ou le grésil est confirmé -> première heure humide entre -6 et +1 °C ce jour-là."""
    out = []
    for d in consensus or []:
        if 'Verglas / grésil' not in (d.get('risques_confirmes') or []):
            continue
        hs = [h for h in hours if str(h['time'].date()) == d['date']]
        wet = [h for h in hs if (h['rain'] >= 0.1 or h['snow'] >= 0.1) and -6 <= h['temp'] <= 1]
        if wet:
            out.append((wet[0]['time'], round(sum(h['rain'] for h in wet), 1)))
        elif hs:
            out.append((hs[0]['time'].replace(hour=max(hs[0]['time'].hour, 6)), 0.0))
    return out


def tmin_after(hours, t, h=8):
    vals = [x['temp'] for x in hours if t <= x['time'] < t + dt.timedelta(hours=h)]
    return min(vals) if vals else None


def iso(t):
    return t.isoformat() if t else None


def plan(models, consensus, ground_cm, now, tz, cfg, snow_plan=()):
    hours = hourly(models, tz, now, cfg['horizon_h'])
    items = []
    for t, mm in freezing(hours, consensus):
        dep, dl = schedule(t, cfg)
        tmin = tmin_after(hours, t)
        prod, why = product(tmin, mm, cfg)
        items.append({'type': 'verglas', 'glace': iso(t), 'depart': iso(dep), 'echeance': iso(dl), 'produit': prod,
                      'temp_min_c': tmin, 'eau_mm': mm,
                      'raison': 'Verglas ou grésil confirmé' + (f' · {why}' if why else '')})
    for start, t, mm, melt in refreezes(hours, ground_cm, cfg):
        dep, dl = schedule(t, cfg)
        tmin = tmin_after(hours, t)
        prod, why = product(tmin, mm, cfg)
        cause = (f'≈ {mm:g} mm de pluie' if mm >= cfg['pluie_min_mm'] else '') + (' et ' if mm >= cfg['pluie_min_mm'] and melt >= cfg['fonte_min_h'] else '') + \
                (f'{melt} h de fonte de la neige au sol' if melt >= cfg['fonte_min_h'] else '')
        items.append({'type': 'regel', 'debut_mouille': iso(start), 'glace': iso(t), 'depart': iso(dep), 'echeance': iso(dl),
                      'produit': prod, 'temp_min_c': tmin, 'eau_mm': mm,
                      'raison': f'{cause[:1].upper()}{cause[1:]}, puis regel sous 0 °C' + (f' · {why}' if why else '')})
    # Un seul épandage par sortie : deux glaces à moins de 6 h d'intervalle sont regroupées (la première l'emporte).
    items.sort(key=lambda x: x['depart'])
    merged = []
    for it in items:
        if merged and dt.datetime.fromisoformat(it['depart']) - dt.datetime.fromisoformat(merged[-1]['depart']) < dt.timedelta(hours=6):
            if it['type'] == 'verglas':
                merged[-1]['raison'] = it['raison'] + ' · ' + merged[-1]['raison']
            continue
        merged.append(it)
    for it in merged:
        dep = dt.datetime.fromisoformat(it['depart'])
        p = next((p for p in snow_plan if p.get('depart') and p.get('statut') == 'sortie'
                  and abs(dt.datetime.fromisoformat(p['depart']) - dep) <= dt.timedelta(hours=3)), None)
        it['avec_deneigement'] = bool(p)
    return merged
