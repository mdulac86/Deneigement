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

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TZ = ZoneInfo('America/Toronto')
NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.astimezone(TZ).date()
LAT, LON = 46.214, -70.486
SOURCES = {
    'eccc': ('Environnement Canada', 'https://meteo.gc.ca/fr/location/index.html?coords=46.214,-70.486'),
    'mm': ('MétéoMédia', 'https://www.meteomedia.com/fr/ville/ca/quebec/saint-prosper/7-jours'),
    'accu': ('AccuWeather', 'https://www.accuweather.com/fr/ca/saint-prosper/g0m/daily-weather-forecast/3390993'),
    'wu': ('Weather Underground', 'https://www.wunderground.com/forecast/ca/saint-prosper/46.214,-70.486'),
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
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

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
    if ('neige' in t and 'pluie' in t) or 'sleet' in t or 'rain/snow' in t:
        return 'Pluie / neige'
    if 'neige' in t or 'snow' in t:
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
        periods.append({'date': str(day), 'label': label, 'text': text, 'snow_cm': qty, 'risk': risk(text)})
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

def accu():
    soup = BeautifulSoup(fetch(SOURCES['accu'][1]), 'html.parser')
    loc = re.search(r'var currentLocation\s*=\s*(\{.*?\});', str(soup))
    if not loc or abs(json.loads(loc[1])['lat']-LAT) > .15 or abs(json.loads(loc[1])['lon']-LON) > .15:
        raise ValueError('Localisation AccuWeather non vérifiée')
    days = []
    for card in soup.select('.daily-wrapper'):
        date = card.select_one('.date.sub')
        if not date:
            date = card.select_one('.date .sub')
        if not date:
            continue
        m = re.search(r'(\d{1,2})/(\d{1,2})', date.get_text())
        if not m:
            continue
        when = dated(int(m[2]), int(m[1]))
        if not TODAY <= when <= TODAY + dt.timedelta(days=7):
            continue
        d = entry(when)
        for selector, key in [('.high', 'high'), ('.low', 'low')]:
            el = card.select_one(selector)
            n = re.search(r'-?\d+', el.get_text()) if el else None
            if n:
                d[key] = float(n[0])
        phrase = card.select_one('.phrase') or card.select_one('.phrase-summary')
        # Garder le texte descriptif, sans recopier les détails éditoriaux.
        text = card.get_text(' ', strip=True)
        m = re.search(r'%\s*(.*?)\s*RealFeel', text)
        d['condition'] = phrase.get_text(' ', strip=True) if phrase else m[1] if m else 'Voir le bulletin source'
        d['risk'] = risk(d['condition'])
        days.append(d)
    if len(days) < 3:
        raise ValueError('Prévisions actuelles AccuWeather non lisibles')
    return {'issued_at': None, 'days': days, 'note': 'Page publique actuelle; heure d’émission non publiée dans les données extraites. Quantités non affichées ici = indisponibles, jamais zéro.'}

def wu():
    soup = BeautifulSoup(fetch(SOURCES['wu'][1]), 'html.parser')
    days = []
    for card in soup.select('a.day-link'):
        href = card.get('href', '')
        m = re.search(r'/([\d.]+),(-?[\d.]+)/date/(\d{4}-\d\d-\d\d)', href)
        if not m or abs(float(m[1])-LAT) > .02 or abs(float(m[2])-LON) > .02:
            continue
        when = dt.date.fromisoformat(m[3])
        if not TODAY <= when <= TODAY+dt.timedelta(days=7):
            continue
        d = entry(when)
        for cls in ('high', 'low'):
            el = card.select_one('.'+cls)
            n = re.search(r'-?\d+', el.text) if el else None
            d[cls] = float(n[0]) if n else None
        el = card.select_one('.condition')
        d['condition'] = el.get_text(' ', strip=True) if el else ''
        d['risk'] = risk(d['condition'])
        # Pas d'interprétation de display-snow sans unité explicite du fournisseur.
        el = card.select_one('.display-qpf.m')
        if el:
            d['rain_mm'] = number(el.get_text(strip=True))
        days.append(d)
    if len(days) < 3:
        raise ValueError('Coordonnées ou dates Weather Underground non vérifiables')
    return {'issued_at': None, 'days': days, 'note': 'Prévisions demandées à 46,21 N / 70,49 O. Station d’observation voisine parfois affichée sous un autre nom. Heure d’émission non fournie; cm de neige non exposés avec une unité explicite.'}

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

def mm():
    fetch(SOURCES['mm'][1])
    raise ValueError('Page publique dynamique : données automatiques non disponibles; consultation directe possible')

def collect_source(key, fn, previous):
    name, url = SOURCES[key]
    try:
        result = fn()
        issued=result.get('issued_at')
        if issued and (NOW-dt.datetime.fromisoformat(issued.replace('Z','+00:00'))).total_seconds()>18*3600:
            return {'id':key,'name':name,'url':url,'status':'stale','fetched_at':stamp(),**result,'error':'Émission de plus de 18 heures : exclue du consensus.'}
        return {'id': key, 'name': name, 'url': url, 'status': 'ok', 'fetched_at': stamp(), **result}
    except Exception as e:
        prev = next((s for s in previous.get('sources', []) if s['id'] == key), {})
        return {'id': key, 'name': name, 'url': url, **{k: prev[k] for k in ('days', 'fetched_at', 'issued_at', 'note', 'periods', 'hourly', 'current') if k in prev}, 'status': 'stale' if prev.get('days') else 'unavailable', 'error': str(e)[:180]}

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
        row = {'date': str(date), 'snow_cm': number(cells[10]), 'snow_flag': cells[11], 'rain_mm': number(cells[8]), 'depth_cm': number(cells[14]), 'source': 'Climat Québec · 7027660'}
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
    months = [(y, m) for m in (10, 11, 12)] + [(y+1, m) for m in range(1, 6)]
    months = [(a,b) for a,b in months if dt.date(a,b,1) <= TODAY]
    errors = []
    # Relecture quotidienne de tous les mois : récupère les corrections tardives.
    if old.get('checked_on') != str(TODAY):
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
    valid = [r for r in rows if r['snow_cm'] is not None]
    end = min(TODAY-dt.timedelta(days=1), dt.date(y+1,5,31))
    expected = max(0, (end-dt.date(y,10,1)).days+1)
    result = {'season': f'{y}–{y+1}', 'start': f'{y}-10-01', 'end': f'{y+1}-05-31', 'records': rows, 'total_cm': round(sum(r['snow_cm'] for r in valid),1) if valid else None, 'last_date': valid[-1]['date'] if valid else None, 'missing_days': max(0, expected-len(valid)), 'checked_on': old.get('checked_on'), 'errors': errors, 'url': QC+str(TODAY), 'note': 'Station automatique 7027660. La source répartit les précipitations en pluie/neige à titre indicatif selon la température horaire. Cumul des valeurs publiées, avec délai; ce n’est pas une mesure de votre cour ni la neige restant au sol.'}
    write(path, result)
    return result

def consensus(sources):
    result = []
    for offset in range(7):
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
        mids = [sum(d['snow_cm'])/2 for d in comparable]
        quantities = {'mean_cm': round(statistics.mean(mids),1) if len(mids)>=2 else None, 'median_cm': round(statistics.median(mids),1) if len(mids)>=2 else None, 'min_cm': min(d['snow_cm'][0] for d in comparable) if mids else None, 'max_cm': max(d['snow_cm'][1] for d in comparable) if mids else None, 'count': len(mids)}
        types = sorted({d['risk'] for d in compared if d.get('risk')})
        highs = [d['high'] for d in compared if d.get('high') is not None]
        lows = [d['low'] for d in compared if d.get('low') is not None]
        result.append({'date':day, 'sources':compared, 'snow':quantities, 'risks':types, 'high_mean':round(statistics.mean(highs),1) if highs else None,'low_mean':round(statistics.mean(lows),1) if lows else None, 'high_range':[min(highs),max(highs)] if highs else None, 'low_range':[min(lows),max(lows)] if lows else None, 'confidence':'Faible' if offset>=3 or len(types)>1 or len(compared)<3 else 'Moyenne', 'confidence_reason':'Accord qualitatif et couverture des sources; précision non encore validée. Fiabilité des cm au sol indéterminée.'})
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

def forecast_plan(sources, days):
    """Modèles horaires -> neige heure par heure (médiane) -> plan de sortie."""
    met_src = next((s for s in sources if s['id'] == 'met' and s['status'] == 'ok'), {})
    models = nwp.collect_models(fetch, met_src, LAT, LON, NOW)
    ok = [x for x in models if x['status'] == 'ok']
    hours = planner.hourly_consensus(ok, TZ)
    cfg = planner.load_config()
    plan = planner.build_plan(hours, cfg, NOW.astimezone(TZ)) if len(ok) >= 1 else []
    # Totaux 00-24 h locaux par jour, seulement pour les heures couvertes par au moins 2 modèles.
    for d in days:
        hs = [h for h in hours if str(h['time'].date()) == d['date'] and h['n'] >= 2]
        d['model_snow'] = {'median_cm': round(sum(h['snow_cm'] for h in hs), 1), 'min_cm': round(sum(h['lo'] for h in hs), 1),
                           'max_cm': round(sum(h['hi'] for h in hs), 1), 'hours': len(hs), 'estimated': True} if len(hs) >= 12 else None
    return {'models': models, 'hourly_snow': serial_hours([{k: h[k] for k in ('time', 'snow_cm', 'lo', 'hi', 'n')} for h in hours]),
            'plan': plan, 'plan_config': cfg}

def main():
    DATA.mkdir(exist_ok=True)
    previous = read(DATA/'weather.json',{})
    fns = {'eccc':eccc, 'met':met, 'accu':accu, 'wu':wu, 'mb':mb, 'mm':mm}
    with futures.ThreadPoolExecutor(max_workers=6) as pool:
        sources = list(pool.map(lambda kv:collect_source(*kv,previous),fns.items()))
    errors=[]
    try:
        raw=fetch('https://api.weather.gc.ca/collections/weather-alerts/items?f=json&bbox=-70.5,46.20,-70.47,46.23&limit=100', True)
        alerts={'status':'ok','fetched_at':stamp(),'items':[f['properties'] for f in raw['features']]}
    except Exception as e:
        alerts={**previous.get('official_alerts',{}),'status':'unavailable','error':str(e)[:120]}
    climate=collect_climate()
    result={'updated_at':stamp(),'location':{'name':'Saint-Prosper · Beauce','lat':LAT,'lon':LON,'timezone':'America/Toronto'},'threshold_cm':5,'sources':sources,'official_alerts':alerts,'climate':climate,'consensus':consensus(sources),'previous_at':previous.get('updated_at')}
    result['changes']=changes(previous,result)
    try:
        result.update(forecast_plan(sources, result['consensus']))
    except Exception as e:  # Le plan ne doit jamais bloquer la collecte principale.
        result.update({'models': [], 'hourly_snow': [], 'plan': [], 'plan_error': str(e)[:200]})
    write(DATA/'weather.json',result)
    # Archives horaires durables : pas d'accumulation de prévisions présentée en relevé.
    snapshot={'updated_at':stamp(),'sources':[{k:s[k] for k in ('id','status','issued_at','fetched_at','days','periods') if k in s} for s in sources], 'consensus':result['consensus'],'changes':result['changes'],'plan':result.get('plan'),'hourly_snow':result.get('hourly_snow'),'models':[{k:x[k] for k in ('id','status','issued_at','hours') if k in x} for x in result.get('models',[])]}
    write(DATA/'archive'/NOW.strftime('%Y-%m-%d')/NOW.strftime('%H.json'),snapshot)
    print(json.dumps({'sources':{s['id']:s['status'] for s in sources},'climate_last':climate['last_date'],'updated_at':stamp()},ensure_ascii=False))
    if not any(s['status']=='ok' for s in sources):
        raise SystemExit('Aucune source actuelle disponible. Dernières valeurs conservées et signalées périmées.')

if __name__=='__main__':
    main()
