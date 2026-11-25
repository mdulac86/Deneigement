"""Collecteur sans clé : données officielles et pages publiques, sans contournement.

Une valeur absente reste None. Aucune conversion pluie -> neige, aucun faux relevé.
"""
import concurrent.futures as futures
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import urllib.request
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import models as nwp  # noqa: E402
import plan as planner  # noqa: E402
import ecmwf  # noqa: E402
import snowdepth  # noqa: E402
import epandage  # noqa: E402
import frost  # noqa: E402
import noaa  # noqa: E402
import routes  # noqa: E402
import trust  # noqa: E402
import erable  # noqa: E402
import motoneige  # noqa: E402
import alerts as notifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TZ = ZoneInfo('America/Toronto')
NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.astimezone(TZ).date()
LAT, LON = 46.214, -70.486
SOURCES = {
    'eccc': ('Environnement Canada', 'https://meteo.gc.ca/fr/location/index.html?coords=46.214,-70.486'),
    'mm': ('MétéoMédia', 'https://www.meteomedia.com/fr/ville/ca/quebec/saint-prosper/7-jours'),
    'mb': ('meteoblue', 'https://www.meteoblue.com/fr/meteo/semaine/saint-prosper_canada_8672691'),
    'met': ('MET Norway', 'https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=46.214&lon=-70.486'),
}
QC = 'https://www.environnement.gouv.qc.ca/climat/donnees/sommaire.asp?cle=7027660&date_selection='

def stamp():
    return NOW.isoformat()

def fetch(url, json_data=False):
    req = urllib.request.Request(url, headers={'User-Agent': 'DeneigementSaintProsper/1.0 (https://github.com/mdulac86/Deneigement)', 'Accept': 'application/json,text/html,*/*'})
    with urllib.request.urlopen(req, timeout=35) as r:
        raw = r.read()
        return json.loads(raw) if json_data else raw.decode(r.headers.get_content_charset() or 'utf-8', errors='replace')

def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def fr(x, default=None):
    if isinstance(x, dict):
        return x.get('fr', x.get('en', default))
    return default if x is None else x

def val(x):
    return fr(x.get('value')) if isinstance(x, dict) else None

def number(s):
    if s is None:
        return None
    m = re.fullmatch(r'\s*([−-]?\d+(?:[.,]\d+)?)\s*', str(s).replace('\xa0', ' '))
    return float(m[1].replace(',', '.').replace('−', '-')) if m else None

def risk(text):
    t = text.lower()
    if re.search(r'vergla|freezing rain|ice pellets|grésil', t):
        return 'Verglas / grésil'
    if ('neige' in t and 'pluie' in t) or 'sleet' in t or 'rain/snow' in t or 'mixte' in t or 'wintry mix' in t:
        return 'Pluie / neige'
    if 'neige' in t or 'snow' in t or 'flocon' in t or 'flurr' in t:
        return 'Neige'
    if re.search(r'pluie|averses|rain', t):
        return 'Pluie'
    return 'Sans risque hivernal identifié'

def snow_range(text):
    # Seulement des quantités explicitement en cm dans un contexte neige.
    if not re.search(r'neige|snow|accumulation', text, re.I):
        return None
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:à|to|-)\s*(\d+(?:[.,]\d+)?)\s*cm\b', text, re.I)
    if m:
        return [float(m[1].replace(',', '.')), float(m[2].replace(',', '.'))]
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*cm\b', text)
    if m:
        n = float(m[1].replace(',', '.'))
        return [n, n]
    return None

def entry(date, **kw):
    return dict(date=str(date), high=None, low=None, snow_cm=None, rain_mm=None, ice_mm=None, condition='', risk='', **kw)

def eccc():
    # qc-b6 correspond au secteur de Saint-Georges incluant Saint-Prosper.
    url = 'https://api.weather.gc.ca/collections/citypageweather-realtime/items/qc-b6?f=json'
    p = fetch(url, True)['properties']
    group = p['forecastGroup']
    issued = fr(group['timestamp'])
    base = dt.datetime.fromisoformat(issued.replace('Z', '+00:00')).astimezone(TZ).date()
    days = {}
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    periods = []
    for f in group.get('forecasts', []):
        label = fr(f.get('period', {}).get('textForecastName'), '')
        eng = f.get('period', {}).get('textForecastName', {}).get('en', '').lower()
        day = base
        for i, name in enumerate(weekdays):
            if name in eng:
                day = base + dt.timedelta(days=(i-base.weekday()) % 7)
                break
        if 'tomorrow' in eng:
            day = base + dt.timedelta(days=1)
        text = fr(f.get('textSummary'), '')
        qty = snow_range(text)
        d = days.setdefault(str(day), entry(day))
        for t in f.get('temperatures', {}).get('temperature', []):
            cl = fr(t.get('class'))
            if cl in ('high', 'low'):
                d[cl] = val(t)
        d['condition'] += (' ' if d['condition'] else '') + text
        # Une quantité nocturne est attachée au jour de début de la nuit.
        # Si une nuit et un jour annoncent chacun une quantité, on les conserve
        # dans les périodes; pas de somme susceptible de compter deux fois un total.
        # Les quantités demeurent dans les périodes officielles : sans début/fin
        # explicites on ne les transforme pas en un total quotidien 00–24 h.
        pop = number(str(val(f.get('abbreviatedForecast', {}).get('pop')) or ''))
        if pop is None:  # sinon dans le texte : « 40 pour cent de probabilité »
            m = re.search(r'(\d+) pour cent de probabilit', text)
            pop = float(m[1]) if m else None
        periods.append({'date': str(day), 'label': label, 'text': text, 'snow_cm': qty, 'risk': risk(text), 'pop': pop})
    for d in days.values():
        d['risk'] = risk(d['condition'])
    hourly = []
    for h in p.get('hourlyForecastGroup', {}).get('hourlyForecasts', []):
        hourly.append({'time': h['timestamp'], 'temp': val(h.get('temperature')), 'condition': fr(h.get('condition'), ''), 'wind': val(h.get('wind', {}).get('speed')), 'gust': val(h.get('wind', {}).get('gust')), 'pop': val(h.get('lop'))})
    return {'issued_at': issued, 'days': list(days.values()), 'periods': periods, 'hourly': hourly, 'current': p.get('currentConditions'), 'region': fr(p.get('region')), 'note': 'Bulletin officiel du secteur de Saint-Georges. Quantités par période; horaires dans le texte original.'}

def met():
    cache_path = DATA / 'met-cache.json'
    cache = read(cache_path, {})
    # Hors pays nordiques, respecter l'intervalle minimal de 3 h de MET Norway.
    age = (NOW-dt.datetime.fromisoformat(cache['fetched_at'])).total_seconds() if cache else 999999
    if age < 10800:
        return cache['result']
    j = fetch(SOURCES['met'][1], True)['properties']
    days, hours = {}, []
    for h in j['timeseries']:
        when = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(TZ)
        data = h['data']; instant = data['instant']['details']
        step = data.get('next_1_hours') or data.get('next_6_hours') or {}
        symbol = step.get('summary', {}).get('symbol_code', '')
        amount = step.get('details', {}).get('precipitation_amount')
        d = days.setdefault(str(when.date()), entry(when.date()))
        t = instant['air_temperature']
        d['high'] = max(d['high'], t) if d['high'] is not None else t
        d['low'] = min(d['low'], t) if d['low'] is not None else t
        r = risk(symbol)
        if r not in d['condition']:
            d['condition'] += (' · ' if d['condition'] else '') + r
        hours.append({'time': h['time'], 'temp': t, 'condition': symbol, 'wind': round(instant['wind_speed']*3.6), 'precip_mm': amount})
    for d in days.values():
        d['risk'] = risk(d['condition'])
    result = {'issued_at': j['meta']['updated_at'], 'days': list(days.values()), 'hourly': hours, 'note': 'Modèle indépendant MET Norway. Pas de conversion des précipitations liquides en cm de neige. Max/min calculés sur les échéances disponibles.'}
    write(cache_path, {'fetched_at': stamp(), 'result': result})
    return result

def dated(month, day):
    candidates = [dt.date(TODAY.year+y, month, day) for y in (-1, 0, 1)]
    return min(candidates, key=lambda d: abs((d-TODAY).days))

def mb():
    soup = BeautifulSoup(fetch(SOURCES['mb'][1]), 'html.parser')
    text = soup.get_text(' ', strip=True)
    if not re.search(r'46[.,]21.*70[.,]48', text):
        raise ValueError('Localisation meteoblue non vérifiée')
    days=[]
    for card in soup.select('.tab-content'):
        t=card.select_one('time[datetime]')
        if not t or not str(TODAY)<=t['datetime']<=str(TODAY+dt.timedelta(days=7)):
            continue
        d=entry(t['datetime'])
        for selector,key in [('.tab-temp-max','high'),('.tab-temp-min','low')]:
            el=card.select_one(selector)
            m=re.search(r'-?\d+',el.text) if el else None
            d[key]=float(m[0]) if m else None
        d['condition']=' / '.join(dict.fromkeys(x.get('alt','') for x in card.select('img.weather-pictogram')))
        d['risk']=risk(d['condition'])
        days.append(d)
    if len(days)<3:
        raise ValueError('Série meteoblue actuelle non lisible')
    return {'issued_at':None,'days':days,'note':'Page publique datée. Quantités liquides non converties en neige. Heure d’émission non fournie.'}

MM_PERIODS = {'Nuit': 0, 'Matin': 6, 'Après-midi': 12, 'Soir': 18}

def amount(text):
    """'2-4 cm' -> [2, 4]; '<1 cm' -> [0, 1]; '0 cm' -> [0, 0]; autre -> None."""
    t = str(text or '').replace(',', '.').replace('\xa0', ' ')
    m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*[-–à]\s*(\d+(?:\.\d+)?)\s*(?:cm|mm)\s*', t)
    if m:
        return [float(m[1]), float(m[2])]
    m = re.fullmatch(r'\s*<\s*(\d+(?:\.\d+)?)\s*(?:cm|mm)\s*', t)
    if m:
        return [0.0, float(m[1])]
    m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:cm|mm)\s*', t)
    return [float(m[1])] * 2 if m else None

def mm_table(html):
    """Tableau schema.org/CSVW publié dans la page (données structurées destinées aux machines)."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            j = json.loads(tag.string or '')
        except ValueError:
            continue
        if not isinstance(j, dict) or j.get('@type') != 'Dataset' or 'Saint-Prosper' not in j.get('name', ''):
            continue
        cols = j['mainEntity']['csvw:tableSchema']['csvw:columns']
        table = {c['csvw:name']: [x.get('csvw:value') for x in c['csvw:cells']] for c in cols}
        n = len(table.get('date', []))
        return [{k: v[i] if i < len(v) else None for k, v in table.items()} for i in range(n)]
    title = soup.title.get_text(strip=True)[:60] if soup.title else 'sans titre'
    n = len(soup.find_all('script', type='application/ld+json'))
    raise ValueError(f'Tableau MétéoMédia non trouvé ({len(html)} car., « {title} », {n} blocs JSON-LD)')

def mm():
    rows = mm_table(fetch(SOURCES['mm'][1]))
    days, periods, hours = {}, [], []
    for r in rows:
        start = MM_PERIODS.get(r.get('timeOfDay'))
        if start is None or not r.get('date'):
            continue
        day = dt.date.fromisoformat(r['date'])
        snow, rain = amount(r.get('snow')), amount(r.get('rain'))
        temp = number(str(r.get('temperature', '')).replace('°C', ''))
        cond = r.get('condition') or ''
        periods.append({'date': str(day), 'label': r['timeOfDay'], 'start_h': start, 'text': cond, 'snow_cm': snow, 'rain_mm': rain, 'temp': temp, 'pop': r.get('pop'), 'risk': risk(cond)})
        d = days.setdefault(str(day), {**entry(day), '_parts': 0})
        d['_parts'] += 1
        if temp is not None:
            d['high'] = temp if d['high'] is None else max(d['high'], temp)
            d['low'] = temp if d['low'] is None else min(d['low'], temp)
        d['condition'] += (' · ' if d['condition'] else '') + cond
        if snow is not None:
            d['snow_cm'] = [round((d['snow_cm'] or [0, 0])[i] + snow[i], 1) for i in (0, 1)]
        mid = None if snow is None else sum(snow) / 2
        for k in range(6):
            t = dt.datetime.combine(day, dt.time(start + k), TZ)
            hours.append({'time': t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'snow_cm': None if mid is None else round(mid / 6, 2), 'temp': temp})
    out = []
    for d in days.values():
        complete = d.pop('_parts') == 4
        d['risk'] = risk(d['condition'])
        # Les 4 périodes (nuit, matin, après-midi, soir) couvrent la journée : total 00-24 h comparable.
        if complete and d['snow_cm'] is not None:
            d['snow_period'] = '00-24-local'
        elif not complete:
            d['snow_cm'] = None
        out.append(d)
    if len(out) < 3:
        raise ValueError('Prévisions MétéoMédia non lisibles')
    return {'issued_at': None, 'days': out, 'periods': periods, 'hours': hours,
            'note': 'Tableau de données structurées publié par MétéoMédia (périodes nuit, matin, après-midi, soir). Quantités en fourchette; heure d’émission non publiée. Découpage horaire des périodes supposé 0-6-12-18 h.'}

RELAY_MAX_H = 7

def relayed(key):
    """Lecture faite par le poste du bureau (scripts/pc_relay.py) si elle a moins de 7 h."""
    relay = read(DATA / 'relay.json', {})
    item = relay.get('sources', {}).get(key, {})
    if item.get('status') != 'ok':
        return None
    when = dt.datetime.fromisoformat(item['fetched_at'])
    if (NOW - when).total_seconds() > RELAY_MAX_H * 3600:
        return None
    return item

def collect_source(key, fn, previous):
    name, url = SOURCES[key]
    item = relayed(key)
    if item:
        r = item['result']
        return {'id': key, 'name': name, 'url': url, 'status': 'ok', 'fetched_at': item['fetched_at'], 'relay': True,
                **r, 'note': (r.get('note', '') + ' Lu par le poste du bureau.').strip()}
    try:
        result = fn()
        issued=result.get('issued_at')
        if issued and (NOW-dt.datetime.fromisoformat(issued.replace('Z','+00:00'))).total_seconds()>18*3600:
            return {'id':key,'name':name,'url':url,'status':'stale','fetched_at':stamp(),**result,'error':'Émission de plus de 18 heures : exclue du consensus.'}
        return {'id': key, 'name': name, 'url': url, 'status': 'ok', 'fetched_at': stamp(), **result}
    except Exception as e:
        prev = next((s for s in previous.get('sources', []) if s['id'] == key), {})
        msg = str(e)
        if '403' in msg:
            msg = 'Le site refuse la lecture automatisée depuis les serveurs du robot (HTTP 403). Consultation directe possible.'
        e = ValueError(msg)
        return {'id': key, 'name': name, 'url': url, **{k: prev[k] for k in ('days', 'fetched_at', 'issued_at', 'note', 'periods', 'hourly', 'current', 'hours') if k in prev}, 'status': 'stale' if prev.get('days') else 'unavailable', 'error': str(e)[:180]}

def climat_month(year, month):
    soup = BeautifulSoup(fetch(QC+f'{year:04}-{month:02}-01'), 'html.parser')
    text = soup.get_text(' ', strip=True)
    if '7027660' not in text or 'Saint-Prosper' not in text:
        raise ValueError('Station Climat Québec non vérifiée')
    rows = []
    for tr in soup.find_all('tr'):
        cells = [x.get_text(' ', strip=True) for x in tr.find_all(['td', 'th'], recursive=False)]
        if len(cells) < 17 or not re.fullmatch(r'\d{2}', cells[0]):
            continue
        date = dt.date(year, month, int(cells[0]))
        if date >= TODAY:
            continue
        # Colonnes réelles avec cellules séparées pour les indicateurs qualité.
        row = {'date': str(date), 'snow_cm': number(cells[10]), 'snow_flag': cells[11], 'rain_mm': number(cells[8]), 'depth_cm': number(cells[14]), 'tmax': number(cells[1]), 'tmin': number(cells[5]), 'source': 'Climat Québec · 7027660'}
        if row['snow_flag'].upper() == 'I':
            row['snow_cm'] = None
        rows.append(row)
    if not rows:
        raise ValueError('Tableau Climat Québec non reconnu')
    return rows

def season_year(day):
    return day.year if day.month >= 10 else day.year-1

def collect_climate():
    y = season_year(TODAY)
    path = DATA / f'season-{y}.json'
    old = read(path, {'records': []})
    records = {r['date']: r for r in old['records']}
    # Octobre à septembre : la neige compte d'octobre à mai; juin à septembre sert à la pluie (chantiers, fiabilité).
    months = [(y, m) for m in (10, 11, 12)] + [(y+1, m) for m in range(1, 10)]
    months = [(a,b) for a,b in months if dt.date(a,b,1) <= TODAY]
    errors = []
    # Relecture quotidienne de tous les mois : récupère les corrections tardives.
    if old.get('checked_on') != str(TODAY) or any('tmax' not in r for r in old.get('records', [])):
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(climat_month, a,b): (a,b) for a,b in months}
            for job in futures.as_completed(jobs):
                try:
                    for row in job.result():
                        records[row['date']] = row
                except Exception as e:
                    errors.append(str(e)[:150])
        old['checked_on'] = str(TODAY) if not errors else old.get('checked_on')
    rows = sorted(records.values(), key=lambda r:r['date'])
    valid = [r for r in rows if r['snow_cm'] is not None and r['date'] <= f'{y+1}-05-31']  # saison de neige
    end = min(TODAY-dt.timedelta(days=1), dt.date(y+1,5,31))
    expected = max(0, (end-dt.date(y,10,1)).days+1)
    result = {'season': f'{y}–{y+1}', 'start': f'{y}-10-01', 'end': f'{y+1}-05-31', 'records': rows, 'total_cm': round(sum(r['snow_cm'] for r in valid),1) if valid else None, 'last_date': valid[-1]['date'] if valid else None, 'missing_days': max(0, expected-len(valid)), 'checked_on': old.get('checked_on'), 'errors': errors, 'url': QC+str(TODAY), 'note': 'Station automatique 7027660. La source répartit les précipitations en pluie/neige à titre indicatif selon la température horaire. Cumul des valeurs publiées, avec délai; ce n’est pas une mesure de votre cour ni la neige restant au sol.'}
    write(path, result)
    return result

def wmean(pairs):
    tot = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / tot if tot else None

def consensus(sources, temp_w=None):
    """temp_w : {source: poids} pour les températures (fiabilité mesurée des max/min, trust.temp_weights)."""
    temp_w = temp_w or {}
    result = []
    for offset in range(14):
        day = str(TODAY+dt.timedelta(days=offset))
        compared = []
        for s in sources:
            if s['status'] != 'ok':
                continue
            d = next((d for d in s.get('days',[]) if d['date']==day), None)
            if d:
                compared.append({'source': s['id'], **d})
        # Les quantités ECCC sont par période (jour/nuit), pas des totaux 00–24h.
        # On les exclut de la moyenne quotidienne tant qu'elles ne sont pas alignées.
        comparable = [d for d in compared if d.get('snow_cm') is not None and d.get('snow_period') == '00-24-local']
        # Une source isolée (plus du double des autres, 8 cm de plus, personne pour la rejoindre) est mise de côté.
        iso = planner.isolated({d['source']: sum(d['snow_cm'])/2 for d in comparable})
        comparable = [d for d in comparable if d['source'] not in iso]
        mids = [sum(d['snow_cm'])/2 for d in comparable]
        quantities = {'mean_cm': round(statistics.mean(mids),1) if len(mids)>=2 else None, 'median_cm': round(statistics.median(mids),1) if len(mids)>=2 else None, 'min_cm': min(d['snow_cm'][0] for d in comparable) if mids else None, 'max_cm': max(d['snow_cm'][1] for d in comparable) if mids else None, 'count': len(mids), 'ecartes': iso}
        types = sorted({d['risk'] for d in compared if d.get('risk')})
        support = {}
        for d in compared:
            if d.get('risk'):
                support.setdefault(d['risk'], []).append(d['source'])
        highs = [d['high'] for d in compared if d.get('high') is not None]
        lows = [d['low'] for d in compared if d.get('low') is not None]
        hw = [(d['high'], temp_w.get(d['source'], 1.0)) for d in compared if d.get('high') is not None]
        lw = [(d['low'], temp_w.get(d['source'], 1.0)) for d in compared if d.get('low') is not None]
        result.append({'date':day, 'sources':compared, 'snow':quantities, 'risks':types, 'risk_sources':support, 'high_mean':round(wmean(hw),1) if hw else None,'low_mean':round(wmean(lw),1) if lw else None, 'high_range':[min(highs),max(highs)] if highs else None, 'low_range':[min(lows),max(lows)] if lows else None, 'confidence':'Faible' if offset>=3 or len(types)>1 or len(compared)<3 else 'Moyenne', 'confidence_reason':'Accord qualitatif et couverture des sources; précision non encore validée. Fiabilité des cm au sol indéterminée.'})
    return result

def changes(old, new):
    if not old:
        return [{'text':'Première collecte : état de référence.', 'important':False}]
    items = []
    for s in new['sources']:
        prev = next((x for x in old.get('sources',[]) if x['id']==s['id']),{})
        if s['status'] != prev.get('status'):
            items.append({'text':f"{s['name']} : disponibilité {prev.get('status','inconnue')} → {s['status']}.", 'important':False})
        if s['status'] != 'ok':
            continue
        for d in s.get('days',[]):
            p = next((x for x in prev.get('days',[]) if x['date']==d['date']),None)
            if not p:
                continue
            if d['risk'] != p['risk']:
                items.append({'text':f"{s['name']} · {d['date']} : {p['risk']} → {d['risk']}.", 'important':True})
            if d.get('snow_cm') and p.get('snow_cm'):
                before, after = sum(p['snow_cm'])/2, sum(d['snow_cm'])/2
                cross = (p['snow_cm'][1]>=5) != (d['snow_cm'][1]>=5)
                if cross or abs(after-before)>=3 or (before>0 and abs(after-before)/before>=.3):
                    items.append({'text':f"{s['name']} · {d['date']} : neige {p['snow_cm']} → {d['snow_cm']} cm (prévision tombée).", 'important':True})
    return items or [{'text':'Aucun changement important dans les données comparables depuis la dernière collecte.', 'important':False}]

def serial_hours(hours):
    return [{**h, 'time': h['time'].isoformat()} for h in hours]

VENT_POUDRERIE = 50  # km/h : rafales qui soulèvent la neige au sol

def ground_snow(result):
    vals = [s['latest']['depth_cm'] for s in (result.get('snow_depth') or {}).get('stations', []) if s.get('latest') and s['latest'].get('depth_cm') is not None]
    recs = [r for r in (result.get('climate') or {}).get('records', []) if r.get('depth_cm') is not None]
    if recs:
        vals.append(recs[-1]['depth_cm'])
    return max(vals) if vals else 0

def wind_risks(result):
    """Rafales prévues par jour (ECCC horaire, MET Norway) et risques de poudrerie ou de glace par grand vent."""
    src = {s['id']: s for s in result['sources'] if s['status'] == 'ok'}
    by_day = {}
    for h in src.get('eccc', {}).get('hourly', []):
        g = h.get('gust') or (h.get('wind') or 0) * 1.5
        day = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(TZ).date().isoformat()
        by_day[day] = max(by_day.get(day, 0), g)
    for h in src.get('met', {}).get('hourly', []):
        if h.get('wind') is None:
            continue
        day = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(TZ).date().isoformat()
        by_day[day] = max(by_day.get(day, 0), h['wind'] * 1.6)  # vent moyen -> rafales
    ground = ground_snow(result) + (result.get('neige_depuis_nettoyage_cm') or 0)
    for d in result['consensus']:
        g = by_day.get(d['date'])
        d['rafales_kmh'] = round(g) if g else None
        if not g or g < VENT_POUDRERIE or ground + ((d.get('model_snow') or {}).get('median_cm') or 0) < 5:
            continue
        hi = d.get('high_mean')
        risk = 'Poudrerie' if hi is not None and hi <= 0 else 'Glace (vent)' if hi is not None and hi <= 3 else None
        if risk and risk not in d['risks']:
            d['risks'] = [r for r in d['risks'] if r != 'Sans risque hivernal identifié'] + [risk]

PAR_TRANCHES = ('nbm', 'mm')  # quantités par 6 h réparties sur chaque heure : exclues des calculs heure par heure
FORTE_PLUIE_MM_H = 1.5   # mm/h (médiane des modèles) : le chantier se remplit d'eau
FORTE_PLUIE_3H = 4.0     # ou 4 mm en 3 h

def heavy_rain(result):
    """Heure locale de début de forte pluie (ou d'orage selon Environnement Canada), jour par jour."""
    per = {}
    wp = {k: v['poids'] for k, v in (result.get('confiance_pluie') or {}).items()}
    for m in result.get('models') or []:
        # Modèles donnés par tranches de 6 h (NBM, MétéoMédia) : répartis également, ils lissent les averses.
        if m.get('status') != 'ok' or m['id'] in PAR_TRANCHES:
            continue
        for h in m.get('hours', []):
            if h.get('precip_mm') is None or (h.get('snow_cm') or 0) > 0:
                continue
            per.setdefault(h['time'], []).append((h['precip_mm'], wp.get(m['id'], 1.0)))
    hours = sorted((dt.datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(TZ), planner.weighted_median(v))
                   for t, v in per.items() if len(v) >= 2)
    storms = {}
    eccc = next((s for s in result['sources'] if s['id'] == 'eccc' and s['status'] == 'ok'), None)
    for h in (eccc or {}).get('hourly', []):
        if re.search(r'orage', h.get('condition') or '', re.I):
            t = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(TZ)
            storms.setdefault(t.date().isoformat(), t)
    lightning = {}
    hrrr = next((m for m in result.get('models') or [] if m['id'] == 'hrrr' and m['status'] == 'ok'), {})
    for h in hrrr.get('hours', []):
        t = dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(TZ)
        if h.get('foudre') and t >= NOW and 6 <= t.hour < 19:
            lightning.setdefault(t.date().isoformat(), t)
    for d in result['consensus']:
        start = None
        for i, (t, mm) in enumerate(hours):
            if t.date().isoformat() != d['date'] or t < NOW:
                continue
            three = sum(x for _, x in hours[i:i + 3])
            if mm >= FORTE_PLUIE_MM_H or three >= FORTE_PLUIE_3H:
                start = (t, round(three, 1))
                break
        storm = storms.get(d['date'])
        if start or storm:
            t = min(x for x in (start and start[0], storm) if x)
            d['forte_pluie'] = {'heure': t.isoformat(), 'mm_3h': start[1] if start else None, 'orage': bool(storm)}
        bolt = lightning.get(d['date'])
        if bolt:  # HRRR seul : affiché et passage horaire, alerte seulement si Environnement Canada annonce aussi un orage
            d['foudre_hrrr'] = bolt.isoformat()

def sap_hours(result):
    """Gel et dégel heure par heure pour l'érablière (médiane des modèles horaires, sans NBM ni MétéoMédia) :
    minimum de la nuit (0 h – 9 h), heures de dégel (> 0 °C) de 8 h à 20 h, et écart entre modèles l'après-midi."""
    per = {}
    for m in result.get('models') or []:
        if m.get('status') != 'ok' or m['id'] in PAR_TRANCHES:
            continue
        for h in m.get('hours', []):
            if h.get('temp') is not None:
                per.setdefault(h['time'], []).append(h['temp'])
    days = {}
    for t, v in per.items():
        if len(v) < 2:
            continue
        lt = dt.datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(TZ)
        days.setdefault(lt.date().isoformat(), []).append((lt.hour, statistics.median(v), max(v) - min(v)))
    for d in result['consensus']:
        hs = days.get(d['date'], [])
        if len({h for h, _, _ in hs}) < 18:
            continue
        night = [t for h, t, _ in hs if h < 9]
        day = [(t, s) for h, t, s in hs if 8 <= h < 20]
        aft = [s for h, _, s in hs if 12 <= h < 17]
        d['seve'] = {'nuit_min': round(min(night), 1) if night else None, 'heures_degel': sum(1 for t, _ in day if t > 0),
                     'max_horaire': round(max(t for t, _ in day), 1) if day else None,
                     'ecart_modeles_c': round(statistics.mean(aft), 1) if aft else None}

def pct(x):
    n = number(str(x or '').replace('%', ''))
    return None if n is None else round(n)

def enrich_days(days, sources, models, pop):
    """Probabilité de précipitations par jour et tendance des modèles européens au-delà de 7 jours."""
    eccc_src = next((s for s in sources if s['id'] == 'eccc' and s['status'] == 'ok'), {})
    mm_src = next((s for s in sources if s['id'] == 'mm' and s['status'] == 'ok'), {})
    ens = {d['date']: d for d in pop.get('jours', [])}
    long_models = [m for m in models if m['id'] in ('ifs', 'aifs', 'met') and m['status'] == 'ok']
    for d in days:
        cands = []
        p = [x.get('pop') for x in eccc_src.get('periods', []) if x['date'] == d['date'] and x.get('pop') is not None]
        if p:
            cands.append((max(p), 'Environnement Canada'))
        p = [pct(x.get('pop')) for x in mm_src.get('periods', []) if x['date'] == d['date']]
        p = [x for x in p if x is not None]
        if p:
            cands.append((max(p), 'MétéoMédia'))
        e = ens.get(d['date'])
        if e and e.get('p1') is not None:
            cands.append((e['p1'], 'ensemble européen'))
        d['pop'] = {'value': max(c[0] for c in cands), 'sources': [c[1] for c in cands],
                    'heavy': e.get('p10') if e else None} if cands else None
        # Tendance : températures et précipitations des modèles quand aucune source quotidienne ne couvre le jour.
        temps, snow, rain = [], [], []
        for m in long_models:
            hs = [h for h in m.get('hours', []) if dt.datetime.fromisoformat(h['time'].replace('Z', '+00:00')).astimezone(TZ).date().isoformat() == d['date']]
            if len(hs) < 18:
                continue
            t = [h['temp'] for h in hs if h.get('temp') is not None]
            if t:
                temps.append((max(t), min(t)))
            snow.append(sum(h.get('snow_cm') or 0 for h in hs))
            rain.append(sum(h.get('precip_mm') or 0 for h in hs))
        if d.get('high_mean') is None and temps:
            d['high_mean'] = round(statistics.mean(t[0] for t in temps), 1)
            d['low_mean'] = round(statistics.mean(t[1] for t in temps), 1)
            d['tendance'] = True
            sn, rn = statistics.median(snow), statistics.median(rain)
            hi = d['high_mean']
            risks = []
            if sn >= 1 and rn - sn >= 2 and hi > 1:
                risks.append('Pluie / neige')
            elif sn >= 1:
                risks.append('Neige')
            elif rn >= 2:
                risks.append('Verglas / grésil' if hi <= 1 and d['low_mean'] < -1 else 'Pluie')
            d['risks'] = risks or ['Sans risque hivernal identifié']
            d['confidence'] = 'Tendance'
            d['confidence_reason'] = 'Au-delà des prévisions quotidiennes : tendance des modèles européens et de MET Norway.'
            if d.get('model_snow') is None and snow:
                d['model_snow'] = {'median_cm': round(sn, 1), 'min_cm': round(min(snow), 1), 'max_cm': round(max(snow), 1), 'estimated': True}

def local_day(iso):
    return dt.datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(TZ).date().isoformat()

def nbm_days(days, models):
    """Plus forte probabilité NBM de 5 cm (et de 2,5 cm) en 6 h parmi les tranches qui commencent ce jour-là."""
    nbm = next((m for m in models if m['id'] == 'nbm' and m['status'] == 'ok'), None)
    for d in days:
        tr = [t for t in (nbm or {}).get('tranches', []) if local_day(t['debut']) == d['date'] and t.get('p_5cm') is not None]
        d['nbm'] = {'p_5cm': max(t['p_5cm'] for t in tr), 'p_2_5cm': max(t['p_2_5cm'] or 0 for t in tr),
                    'snow_cm': round(sum(t['snow_cm'] or 0 for t in tr), 1)} if tr else None

def trusted_view(p, hours, models, table):
    """Ce que disent les modèles les plus fiables sur l'épisode : total prévu par chacun, du plus fiable au moins fiable."""
    a = dt.datetime.fromisoformat(p['debut']) if p.get('debut') else None
    b = dt.datetime.fromisoformat(p['fin']) if p.get('fin') else None
    if not a or not b:
        return []
    names = {m['id']: m['name'] for m in models}
    tot = {}
    for h in hours:
        if a <= h['time'] < b:
            for k, v in h['models'].items():
                tot[k] = tot.get(k, 0) + v
    rows = [{'id': k, 'nom': names.get(k, k), 'cm': round(v, 1), 'poids': (table.get(k) or {}).get('poids'),
             'statut': (table.get(k) or {}).get('statut')} for k, v in tot.items()]
    return sorted(rows, key=lambda r: -(r['poids'] or 0))[:4]

def confirm_risks(result):
    """Risques qui déclenchent une alerte : annoncés par Environnement Canada (source officielle),
    par au moins 2 sources, ou par une source mesurée et fiable (trust.py). Les risques ajoutés par les
    modèles (vent, verglas HRRR confirmé, tendance) sont déjà filtrés à la source.
    Tous les risques restent affichés; seuls les confirmés déclenchent une alerte."""
    table = result.get('confiance') or {}
    for d in result['consensus']:
        sup = d.get('risk_sources') or {}
        ok, doubt = [], []
        for r in d['risks']:
            srcs = sup.get(r)
            if not srcs or 'eccc' in srcs or len(set(srcs)) >= 2 or any(trust.reliable(table, s) for s in srcs):
                ok.append(r)
            else:
                doubt.append({'risque': r, 'source': srcs[0]})
        d['risques_confirmes'] = ok
        d['risques_a_confirmer'] = doubt

def freezing_rain(result):
    """Pluie verglaçante prévue par HRRR (2 h ou plus dans la journée).
    Ajoutée aux risques (donc aux alertes) seulement si HRRR est une source mesurée et fiable;
    sinon elle reste affichée « à confirmer », sans alerte."""
    hrrr = next((m for m in result.get('models') or [] if m['id'] == 'hrrr' and m['status'] == 'ok'), None)
    if not hrrr:
        return
    sure = trust.reliable(result.get('confiance') or {}, 'hrrr')
    per = {}
    for h in hrrr.get('hours', []):
        if h.get('verglas'):
            per[local_day(h['time'])] = per.get(local_day(h['time']), 0) + 1
    for d in result['consensus']:
        n = per.get(d['date'], 0)
        d['verglas_hrrr_h'] = n or None
        if n < 2:
            continue
        confirmed = 'Verglas / grésil' in d['risks']  # déjà annoncé par une autre source
        d['verglas_hrrr_confirme'] = confirmed or sure
        if sure and not confirmed:
            d['risks'] = [r for r in d['risks'] if r != 'Sans risque hivernal identifié'] + ['Verglas / grésil']

RAPIDE = os.environ.get('RAPIDE') == '1'  # passage horaire pendant une tempête (voir tempete())
LENTS = ('hrdps', 'rdps', 'gfs')  # modèles relancés aux 6 h : réutilisés pendant un passage rapide

TEMPETE_H = 36  # passages horaires si une sortie peut commencer dans les 36 h

def tempete(result, now=None):
    """Faut-il passer toutes les heures ? Oui si une sortie (prévue ou possible) est en cours ou
    commence dans les 36 h, ou si Environnement Canada a une alerte en vigueur pour le secteur."""
    now = now or NOW
    for p in result.get('plan') or []:
        if p.get('statut') not in ('sortie', 'possible'):
            continue
        a = dt.datetime.fromisoformat(p.get('debut') or p['depart'])
        b = dt.datetime.fromisoformat(p.get('fin') or p.get('fin_tournee') or p['depart'])
        if a <= now + dt.timedelta(hours=TEMPETE_H) and b + dt.timedelta(hours=2) >= now:
            return {'active': True, 'raison': ('Sortie prévue' if p['statut'] == 'sortie' else 'Sortie possible') + ' : ' + p['depart'],
                    'jusqu_a': (b + dt.timedelta(hours=2)).isoformat()}
    if (result.get('official_alerts') or {}).get('items'):
        return {'active': True, 'raison': 'Alerte officielle d’Environnement Canada', 'jusqu_a': None}
    if 4 <= now.astimezone(TZ).month <= 11:  # saison des chantiers : forte pluie, orage ou foudre de jour
        for d in result.get('consensus') or []:
            for what, iso in (('Forte pluie ou orage', (d.get('forte_pluie') or {}).get('heure')), ('Foudre possible (HRRR)', d.get('foudre_hrrr'))):
                if not iso:
                    continue
                t = dt.datetime.fromisoformat(iso)
                if now - dt.timedelta(hours=3) <= t <= now + dt.timedelta(hours=TEMPETE_H) and 6 <= t.astimezone(TZ).hour < 19:
                    return {'active': True, 'raison': f'{what} vers {t.astimezone(TZ):%H h %M} le {t.astimezone(TZ):%d/%m}',
                            'jusqu_a': (t + dt.timedelta(hours=6)).isoformat()}
    return {'active': False}

def merge_tail(new, old):
    """HRRR rapide (18 h) complété par la fin du dernier run de 48 h."""
    if not old or old.get('status') != 'ok':
        return new
    last = max(h['time'] for h in new['hours'])
    return {**new, 'hours': new['hours'] + [h for h in old.get('hours', []) if h['time'] > last],
            'note': new['note'] + ' Passage rapide : 18 premières heures du run horaire le plus récent, suite du dernier run de 48 h.'}

def slow_models(met_src, previous):
    """Passage complet : tous les modèles. Passage rapide : HRDPS, RDPS et GFS repris du dernier passage."""
    prev = {m['id']: m for m in (previous or {}).get('models', []) if m.get('status') == 'ok'}
    if not RAPIDE or not all(k in prev for k in LENTS):
        return nwp.collect_models(fetch, met_src, LAT, LON, NOW)
    out = [{**prev[k], 'reutilise': True} for k in LENTS]
    try:
        out.append({'id': 'met', 'name': 'MET Norway', 'status': 'ok', 'fetched_at': stamp(), 'note': nwp.NOTE, **nwp.met_model(met_src)})
    except Exception as e:
        out.append({'id': 'met', 'name': 'MET Norway', 'status': 'unavailable', 'fetched_at': stamp(), 'hours': [], 'error': str(e)[:200]})
    return out

def forecast_plan(sources, days, previous=None):
    """Modèles horaires -> neige heure par heure (médiane) -> plan de sortie."""
    met_src = next((s for s in sources if s['id'] == 'met' and s['status'] == 'ok'), {})
    prev_hrrr = next((m for m in (previous or {}).get('models', []) if m['id'] == 'hrrr'), None)
    hrrr_h = noaa.HRRR_RAPIDE if RAPIDE else noaa.HRRR_HORIZON
    with futures.ThreadPoolExecutor(max_workers=2) as pool:  # NBM et HRRR : ~1 min chacun, en parallèle
        us = {'nbm': pool.submit(noaa.nbm, LAT, LON, NOW), 'hrrr': pool.submit(noaa.hrrr, LAT, LON, NOW, hrrr_h)}
        models = slow_models(met_src, previous)
        for k, name in (('nbm', 'NBM 2,5 km · NOAA (synthèse)'), ('hrrr', 'HRRR 3 km · NOAA')):
            try:
                r = us[k].result()
                if k == 'hrrr' and RAPIDE:
                    r = merge_tail(r, prev_hrrr)
                models.append({'id': k, 'name': name, 'status': 'ok', 'fetched_at': stamp(), **r})
            except Exception as e:
                models.append({'id': k, 'name': name, 'status': 'unavailable', 'fetched_at': stamp(), 'hours': [], 'error': str(e)[:200]})
    cache = read(DATA / 'ecmwf-cache.json', {})
    try:
        ifs, _ = ecmwf.cached(cache, 'ifs', NOW, lambda: ecmwf.deterministic(LAT, LON, NOW))
        models.append({'id': 'ifs', 'name': 'ECMWF IFS (européen)', 'status': 'ok', 'fetched_at': stamp(), **ifs})
    except Exception as e:
        models.append({'id': 'ifs', 'name': 'ECMWF IFS (européen)', 'status': 'unavailable', 'fetched_at': stamp(), 'hours': [], 'error': str(e)[:200]})
    try:
        aifs, _ = ecmwf.cached(cache, 'aifs', NOW, lambda: ecmwf.deterministic(LAT, LON, NOW, 'aifs-single'))
        models.append({'id': 'aifs', 'name': 'ECMWF AIFS (européen, IA)', 'status': 'ok', 'fetched_at': stamp(), **aifs})
    except Exception as e:
        models.append({'id': 'aifs', 'name': 'ECMWF AIFS (européen, IA)', 'status': 'unavailable', 'fetched_at': stamp(), 'hours': [], 'error': str(e)[:200]})
    try:
        ens, _ = ecmwf.cached(cache, 'ens', NOW, lambda: ecmwf.ensemble(LAT, LON, NOW, TZ))
        ensemble = {'status': 'ok', **ens}
    except Exception as e:
        ensemble = {'status': 'unavailable', 'error': str(e)[:200], 'jours': []}
    try:
        pop, _ = ecmwf.cached(cache, 'pop', NOW, lambda: ecmwf.precip_probability(LAT, LON, NOW, TZ))
    except Exception as e:
        pop = {'jours': [], 'error': str(e)[:200]}
    write(DATA / 'ecmwf-cache.json', cache)
    mm_src = next((s for s in sources if s['id'] == 'mm' and s['status'] == 'ok' and s.get('hours')), None)
    if mm_src:
        models.append({'id': 'mm', 'name': 'MétéoMédia (cm publiés)', 'status': 'ok', 'fetched_at': mm_src['fetched_at'],
                       'note': 'cm publiés par MétéoMédia par période de 6 h, répartis également sur chaque heure.', 'hours': mm_src['hours']})
    ok = [x for x in models if x['status'] == 'ok']
    # Poids de confiance recalculés à chaque passage à partir du tableau de fiabilité (prévu vs mesuré).
    scores = read(DATA / 'verification' / 'scores.json', {})
    table = trust.weights(scores, [m['id'] for m in models])
    table_pluie = trust.weights(scores, [m['id'] for m in models], 'pluie')
    for m in models:
        m['confiance'] = table.get(m['id'])
        m['confiance_pluie'] = table_pluie.get(m['id'])
    hours = planner.hourly_consensus(ok, TZ, {k: v['poids'] for k, v in table.items()})
    cfg = planner.load_config()
    # Petites chutes déjà au sol : relevés publiés + neige des modèles depuis le dernier relevé.
    records = read(DATA / f'season-{season_year(TODAY)}.json', {}).get('records', [])
    carry = planner.carry_from_records(records, cfg)
    last = max((r['date'] for r in records if r.get('snow_cm') is not None), default=None)
    since = dt.datetime.combine(dt.date.fromisoformat(last) + dt.timedelta(days=1), dt.time(0), TZ) if last else NOW.astimezone(TZ)
    carry += sum(h['snow_cm'] for h in hours if since <= h['time'] < NOW.astimezone(TZ))
    melt_days = [d['date'] for d in days if (d.get('high_mean') or 0) >= 4]
    plan = planner.build_plan(hours, cfg, NOW.astimezone(TZ), round(carry, 1), melt_days) if len(ok) >= 1 else []
    # Totaux 00-24 h locaux par jour, seulement pour les heures couvertes par au moins 2 modèles.
    for d in days:
        hs = [h for h in hours if str(h['time'].date()) == d['date'] and h['n'] >= 2]
        d['model_snow'] = {'median_cm': round(sum(h['snow_cm'] for h in hs), 1), 'min_cm': round(sum(h['lo'] for h in hs), 1),
                           'max_cm': round(sum(h['hi'] for h in hs), 1), 'hours': len(hs), 'estimated': True} if len(hs) >= 12 else None
    by_day = {d['date']: d for d in ensemble.get('jours', [])}
    for d in days:
        d['ensemble'] = by_day.get(d['date'])
    nbm_days(days, models)
    enrich_days(days, sources, models, pop)
    for p in plan:
        t = p.get('seuil_atteint') or (p.get('seuil_fourchette') or [None])[0] or p.get('debut')
        p['ensemble'] = by_day.get(t[:10]) if t else None
        p['fiables'] = trusted_view(p, hours, models, table)
        nbm_m = next((m for m in models if m['id'] == 'nbm' and m['status'] == 'ok'), None)
        p['probabilite'], p['probabilite_detail'] = planner.probability(
            p, hours, {k: v['poids'] for k, v in table.items()}, ensemble.get('jours', []), (nbm_m or {}).get('tranches', []), cfg)
    planner.apply_probability(plan, cfg)
    return {'confiance': table, 'confiance_pluie': table_pluie, 'ensemble': ensemble, 'precip_probability': pop, 'models': models, 'hourly_snow': serial_hours([{k: h[k] for k in ('time', 'snow_cm', 'lo', 'hi', 'n')} for h in hours]),
            'plan': plan, 'plan_config': cfg, 'neige_depuis_nettoyage_cm': round(carry, 1)}

def main():
    DATA.mkdir(exist_ok=True)
    previous = read(DATA/'weather.json',{})
    fns = {'eccc':eccc, 'met':met, 'mb':mb, 'mm':mm}  # AccuWeather et Weather Underground retirés : refusent toute lecture automatisée
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        sources = list(pool.map(lambda kv:collect_source(*kv,previous),fns.items()))
    errors=[]
    try:
        raw=fetch('https://api.weather.gc.ca/collections/weather-alerts/items?f=json&bbox=-70.5,46.20,-70.47,46.23&limit=100', True)
        alerts={'status':'ok','fetched_at':stamp(),'items':[f['properties'] for f in raw['features']]}
    except Exception as e:
        alerts={**previous.get('official_alerts',{}),'status':'unavailable','error':str(e)[:120]}
    climate=collect_climate()
    # Températures pondérées par la fiabilité mesurée de chaque site (max/min prévus la veille vs mesurés).
    temp_table=trust.temp_weights(read(DATA/'verification'/'scores.json',{}),[s['id'] for s in sources])
    result={'updated_at':stamp(),'location':{'name':'Saint-Prosper · Beauce','lat':LAT,'lon':LON,'timezone':'America/Toronto'},'threshold_cm':planner.load_config()['seuil_cm'],'sources':sources,'official_alerts':alerts,'climate':climate,'consensus':consensus(sources,{k:v['poids'] for k,v in temp_table.items()}),'previous_at':previous.get('updated_at'),'confiance_temperatures':temp_table}
    result['changes']=changes(previous,result)
    result['saison_estimation']=read(ROOT/'config'/'saison.json',None)
    try:  # première coulée : estimation automatique refaite chaque automne (+ estimation manuelle éventuelle)
        est=read(DATA/'erable-estimation.json',None)
        if not RAPIDE:
            gj=lambda u: fetch(u, True)
            est,changed=erable.auto(est,gj,climat_month,TODAY)
            if changed:
                write(DATA/'erable-estimation.json',est)
        result['erable']=erable.merge(read(ROOT/'config'/'erable.json',{}),est,TODAY)
    except Exception as e:
        print('érable :',e)
        result['erable']=read(ROOT/'config'/'erable.json',None)
    try:
        result['snow_depth']=snowdepth.collect(fetch,NOW)
    except Exception as e:
        result['snow_depth']={'stations':[],'error':str(e)[:150]}
    try:
        vent=snowdepth.daily_gusts(result['snow_depth'].get('stations',[]),TZ,read(DATA/'vent-saison.json',{}))
        write(DATA/'vent-saison.json',vent)
        result['vent_saison']=vent
    except Exception as e:
        print('vent :',e)
    try:
        pluie=snowdepth.daily_precip(result['snow_depth'].get('stations',[]),TZ,read(DATA/'pluie-obs.json',{}))
        write(DATA/'pluie-obs.json',pluie)
        result['pluie_obs']=pluie
    except Exception as e:
        print('pluie observée :',e)
    try:
        result.update(forecast_plan(sources, result['consensus'], previous))
    except Exception as e:  # Le plan ne doit jamais bloquer la collecte principale.
        result.update({'models': [], 'hourly_snow': [], 'plan': [], 'plan_error': str(e)[:200]})
    try:
        wind_risks(result)
    except Exception as e:
        print('risques de vent :', e)
    try:
        heavy_rain(result)
    except Exception as e:
        print('forte pluie :', e)
    try:
        freezing_rain(result)
    except Exception as e:
        print('pluie verglaçante :', e)
    try:
        confirm_risks(result)
    except Exception as e:
        print('risques confirmés :', e)
    try:  # épandage sel + calcium / abrasif : verglas confirmé, ou pluie / fonte puis regel (config/epandage.json)
        cfg_ep = epandage.load_config()
        result['epandage'] = epandage.plan(result.get('models') or [], result['consensus'], ground_snow(result),
                                           NOW.astimezone(TZ), TZ, cfg_ep, result.get('plan') or [])
        result['epandage_config'] = cfg_ep
    except Exception as e:
        print('épandage :', e)
    try:
        sap_hours(result)
    except Exception as e:
        print('érable (heures) :', e)
    try:
        nbm = next((m for m in result.get('models') or [] if m['id'] == 'nbm' and m['status'] == 'ok'), None)
        result['nbm_proba'] = {'run': nbm['run'], 'tranches': nbm['tranches']} if nbm else None
    except Exception as e:
        print('NBM :', e)
    try:  # probabilité de précipitation jour (7 h-19 h) et nuit (19 h-7 h), au pour cent près
        result['pop12'] = previous.get('pop12') if RAPIDE and previous.get('pop12') else noaa.nbm_pop12(LAT, LON, NOW)
    except Exception as e:
        print('NBM 12 h :', e)
        result['pop12'] = previous.get('pop12')
    try:
        result['routes'] = routes.collect(lambda u: fetch(u, True), LAT, LON, stamp(), previous.get('routes'))
    except Exception as e:
        result['routes'] = {'status': 'unavailable', 'error': str(e)[:150]}
    try:
        prev_gel=read(DATA/'gel-sol.json',None)
        if prev_gel and prev_gel.get('fetched')==str(TODAY) and prev_gel.get('status')=='ok':
            gel={**prev_gel,'projection':frost.project(prev_gel['gel_m'],[d for d in result['consensus'] if d['date']>prev_gel['date']][:10])}
        else:
            gel={**frost.collect(fetch,TODAY,result['consensus'],prev_gel),'fetched':str(TODAY)}
        write(DATA/'gel-sol.json',gel)
        result['gel_sol']=gel
    except Exception as e:
        print('gel au sol :', e)
    try:  # motoneige hors-piste : passages complets seulement, en saison (config/motoneige.json)
        cfg_moto=read(ROOT/'config'/'motoneige.json',None)
        if cfg_moto and motoneige.in_season(cfg_moto,TODAY):
            if RAPIDE and previous.get('motoneige'):
                result['motoneige']=previous['motoneige']
            elif not RAPIDE:
                moto,hist=motoneige.collect(cfg_moto,fetch,nwp,NOW,TZ,read(DATA/'motoneige.json',{}).get('historique',[]))
                write(DATA/'motoneige.json',{'historique':hist})
                result['motoneige']=moto
    except Exception as e:
        print('motoneige :',e)
        if previous.get('motoneige'):
            result['motoneige']={**previous['motoneige'],'status':'stale','error':str(e)[:150]}
    result['tempete']=tempete(result)
    result['passage']='rapide' if RAPIDE else 'complet'
    write(DATA/'weather.json',result)
    try:
        sent=notifier.run(result,DATA/'alerts-state.json',today=TODAY)
        result['alerts_sent']=sent
    except Exception as e:
        print('alertes :',e)
    # Archives horaires durables : pas d'accumulation de prévisions présentée en relevé.
    if RAPIDE:  # les archives (tableau de fiabilité) ne gardent que les passages complets
        print(json.dumps({'passage':'rapide','tempete':result['tempete'],'updated_at':stamp()},ensure_ascii=False))
        return
    snapshot={'updated_at':stamp(),'sources':[{k:s[k] for k in ('id','status','issued_at','fetched_at','days','periods') if k in s} for s in sources], 'consensus':result['consensus'],'changes':result['changes'],'plan':result.get('plan'),'hourly_snow':result.get('hourly_snow'),'models':[{k:x[k] for k in ('id','status','issued_at','hours') if k in x} for x in result.get('models',[])]}
    write(DATA/'archive'/NOW.strftime('%Y-%m-%d')/NOW.strftime('%H.json'),snapshot)
    print(json.dumps({'sources':{s['id']:s['status'] for s in sources},'climate_last':climate['last_date'],'updated_at':stamp()},ensure_ascii=False))
    if not any(s['status']=='ok' for s in sources):
        raise SystemExit('Aucune source actuelle disponible. Dernières valeurs conservées et signalées périmées.')

if __name__=='__main__':
    main()
