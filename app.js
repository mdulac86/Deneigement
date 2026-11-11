'use strict';
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=v=>v==null?'—':new Intl.NumberFormat('fr-CA',{maximumFractionDigits:1}).format(v);
const local=(v,opts={})=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',...opts}).format(new Date(v)):'Non publiée';
const dayLabel=v=>new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'short',month:'short',day:'numeric'}).format(new Date(v+'T12:00:00-05:00'));
const dateOnly=v=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',day:'numeric',month:'short'}).format(new Date(v+'T12:00:00-05:00')):'—';
let state=null,selected=0,map=null,timer=null,radarLayer='RADAR_1KM_RRAI';
function stale(s){return s.status!=='ok'||(s.issued_at?Date.now()-Date.parse(s.issued_at)>18*3600000:Date.now()-Date.parse(s.fetched_at)>(s.relay?7:3)*3600000)}
const ICONS={"ice": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><path d=\"M14 36l4 6M22 36l4 6M30 36l4 6\" stroke=\"#FF6B35\" stroke-width=\"2.5\" stroke-linecap=\"round\"/></svg>", "mix": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><g stroke=\"#7CC4F0\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M17 36v8M13.5 38l7 4M13.5 42l7-4\"/></g><path d=\"M30 37l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/></svg>", "snow": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><g stroke=\"#7CC4F0\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M16 36v8M12.5 38l7 4M12.5 42l7-4\"/></g><g stroke=\"#7CC4F0\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M31 36v8M27.5 38l7 4M27.5 42l7-4\"/></g></svg>", "rain": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><path d=\"M16 37l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/><path d=\"M24 39l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/><path d=\"M32 37l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/></svg>", "cloud": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><circle cx=\"16\" cy=\"17\" r=\"7\" fill=\"#FFB81C\"/><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/></svg>"};
function symbol(types){let t=types.join(' ');return /Verglas/.test(t)?ICONS.ice:/Pluie \/ neige/.test(t)?ICONS.mix:/Neige/.test(t)?ICONS.snow:/Pluie/.test(t)?ICONS.rain:ICONS.cloud}
function displayQty(d){if(!d?.snow_cm)return '—';return d.snow_cm[0]===d.snow_cm[1]?n(d.snow_cm[0])+' cm':n(d.snow_cm[0])+'–'+n(d.snow_cm[1])+' cm'}
async function load(){
  $('refresh').disabled=true;
  try{
    const r=await fetch('data/weather.json',{cache:'no-store'});if(!r.ok)throw new Error('Données indisponibles');
    const j=await r.json();if(!Array.isArray(j.sources)||!j.climate)throw new Error('Format de données non reconnu');state=j;
    try{const s=await fetch('data/verification/scores.json',{cache:'no-store'});if(s.ok)j.scores=await s.json()}catch{}
    localStorage.setItem('deneigement-last-data',JSON.stringify(j));render();
  }catch(e){
    if(!state){try{state=JSON.parse(localStorage.getItem('deneigement-last-data'))}catch{}}
    if(state)render();
    $('error').hidden=false;$('error').textContent=state?'Connexion impossible. Dernières données conservées : '+local(state.updated_at)+'. Vérifie les sources avant une sortie.':'Impossible de charger la météo. Le robot doit effectuer sa première collecte. Réessaie ou consulte les sources officielles.';
    $('connection').textContent='Hors ligne';
  }finally{$('refresh').disabled=false}
}
function render(){
  const age=(Date.now()-Date.parse(state.updated_at))/3600000;
  $('error').hidden=age<=3;
  if(age>3)$('error').textContent='Données anciennes : dernière collecte le '+local(state.updated_at)+'. Le robot semble en retard; consulte les bulletins originaux.';
  $('connection').textContent=age>3?'À actualiser':'Données à jour';$('connection').className='tag '+(age>3?'amber':'green');
  $('asof').textContent='POSTE MÉTÉO · COLLECTE DU '+local(state.updated_at).toUpperCase()+' HNE/HAE';
  const active=state.sources.filter(s=>!stale(s));$('source-count').textContent=active.length+' / 6';
  const c=state.climate; $('season-total').textContent=n(c.total_cm)+(c.total_cm!=null?' cm':'');$('winter-total').textContent=$('season-total').textContent;
  const lag=c.last_date?Math.floor((Date.now()-Date.parse(c.last_date+'T12:00:00-05:00'))/86400000):null;
  $('season-lag').textContent=c.last_date?'Publié jusqu’au '+dateOnly(c.last_date):'Relevés non disponibles';
  $('winter-last').textContent=dateOnly(c.last_date);$('winter-delay').textContent=lag==null?'En attente de publication':'Décalage d’environ '+lag+' jour'+(lag>1?'s':'');
  $('winter-missing').textContent=c.missing_days;$('winter-label').textContent='Hiver '+c.season+' · station Saint-Prosper 7027660';$('climate-note').textContent=c.note;$('climate-link').href=c.url;
  const next=state.consensus.slice(0,3);const ice=next.some(d=>d.risks.includes('Verglas / grésil')),mixed=next.some(d=>d.risks.includes('Pluie / neige')),snow=next.some(d=>d.risks.includes('Neige'));
  const hasOfficial=state.official_alerts?.items?.length>0;
  const threshold=next.some(d=>d.snow.max_cm>=5);
  const title=hasOfficial?'Une alerte officielle vise le secteur.':ice?'Verglas ou grésil à surveiller.':mixed?'Épisode de pluie et neige à surveiller.':threshold?'Le seuil de 5 cm est dans la fourchette.':snow?'De la neige figure aux prévisions.':'Pas de risque hivernal identifié dans les sources disponibles.';
  const label=hasOfficial?'ALERTE OFFICIELLE':ice||mixed||snow||threshold?'VIGILANCE · PROCHAINES 72 H':'ÉTAT DES PRÉVISIONS';
  $('status').className='signal '+(hasOfficial?'alert':ice||mixed||snow||threshold?'watch':'calm');$('status').innerHTML='<div><span class="tag '+(hasOfficial?'':ice||mixed||snow||threshold?'amber':'green')+'">'+label+'</span><h2>'+title+'</h2><p>Seuil opérationnel : 5 cm de nouvelle neige au sol. '+(threshold?'Les cm annoncés concernent la neige tombée; le seuil réel au sol reste à vérifier.':'Les quantités comparables ne permettent pas de confirmer l’atteinte des 5 cm au sol.')+'</p></div>';
  $('days').innerHTML=state.consensus.map((d,i)=>'<button class="day '+(selected===i?'active':'')+'" data-day="'+i+'" aria-pressed="'+(selected===i)+'"><span class="date">'+esc(dayLabel(d.date))+'</span><span class="symbol">'+symbol(d.risks)+'</span><strong>'+n(d.high_mean)+'° <span class="muted">/ '+n(d.low_mean)+'°</span></strong><small>'+d.sources.length+' sources · '+esc(d.confidence)+'</small><small>Neige : '+(d.snow.mean_cm!=null?n(d.snow.mean_cm)+' cm':d.model_snow?'≈ '+n(d.model_snow.median_cm)+' cm (modèles)':'non chiffrable')+'</small>'+(d.ensemble?'<small class="'+(d.ensemble.prob_5cm>=30?'ens-high':'')+'">5 cm+ : '+d.ensemble.prob_5cm+' % (ensemble)</small>':'')+'</button>').join('');
  document.querySelectorAll('[data-day]').forEach(b=>b.addEventListener('click',()=>{selected=Number(b.dataset.day);render()}));
  renderPlan();renderComparison();renderOfficial();renderWinter();renderSources();renderReliability();
  $('previous').textContent=state.previous_at?'Depuis '+local(state.previous_at):'État de référence';$('changes').innerHTML=state.changes.map(c=>'<li>'+esc(c.text)+'</li>').join('');
}
function renderComparison(){
  const d=state.consensus[selected], q=d.snow;$('compare-title').textContent=dayLabel(d.date);$('compare-confidence').textContent='Confiance '+d.confidence.toLowerCase();
  $('mean-snow').textContent=q.mean_cm==null?'Indéterminée':n(q.mean_cm)+' cm';$('mean-note').textContent=q.count+' sources avec cm et périodes compatibles · '+dateOnly(d.date);
  let summary=q.mean_cm==null?'<b>Moyenne de neige indisponible</b><br><span class="muted">Moins de 2 sources avec une quantité en cm pour la même période. Les bulletins restent consultables ci-contre.</span>':'<b>Moyenne '+n(q.mean_cm)+' cm</b> · médiane '+n(q.median_cm)+' cm<br>Fourchette '+n(q.min_cm)+'–'+n(q.max_cm)+' cm · '+q.count+' sources';
  let html='<div class="summary-strip">'+summary+'</div>';
  if(d.high_range)html+='<p class="footnote">Maximum : moyenne '+n(d.high_mean)+' °C · sources de '+n(d.high_range[0])+' à '+n(d.high_range[1])+' °C. '+esc(d.confidence_reason)+'</p>';
  for(const source of state.sources){const row=d.sources.find(x=>x.source===source.id);html+='<div class="compare-row"><div class="source-name"><a href="'+esc(source.url)+'" target="_blank" rel="noopener">'+esc(source.name)+' ↗</a><small>'+(!row||stale(source)?'Hors consensus':'Consultée '+local(source.fetched_at,{month:undefined,day:undefined}))+'</small></div><div>'+esc(row?.risk||'Données indisponibles')+'<small>'+n(row?.high)+'° / '+n(row?.low)+'°</small></div><div class="qty">'+displayQty(row)+'<small>neige</small></div></div>'}
  $('compare').innerHTML=html;
}
function renderOfficial(){
 const s=state.sources.find(s=>s.id==='eccc');
 let html='';
 if(state.official_alerts?.status!=='ok')html+='<p class="official-alert">État des alertes officielles non vérifié.</p>';
 else if(!state.official_alerts.items.length)html+='<p class="muted">Aucune alerte officielle retournée pour les coordonnées lors de la collecte.</p>';
 else for(const a of state.official_alerts.items){let strings=[];function walk(o){if(!o||typeof o!=='object')return;for(const [k,v]of Object.entries(o)){if(['headline','description','event','text','textSummary'].includes(k)){if(typeof v==='string')strings.push(v);else if(v?.fr)strings.push(v.fr)}else if(typeof v==='object')walk(v)}}walk(a);html+='<div class="official-alert">'+esc(strings.slice(0,3).join(' · ')||'Alerte officielle : consulter Environnement Canada')+'</div>'}
 html+='<p class="footnote">Émis : '+local(s?.issued_at)+' · '+esc(s?.region||'secteur de Saint-Georges')+'</p>';
 const periods=(s?.periods||[]).filter(p=>p.date>=state.consensus[0].date).slice(0,7);
 html+=periods.map((p,i)=>'<details '+(i<3?'open':'')+'><summary>'+esc(p.label)+' · '+esc(p.risk)+'</summary><p>'+esc(p.text)+'</p></details>').join('');
 if(!periods.length)html+='<p>Bulletin indisponible. Consulte la source officielle.</p>';
 html+='<p class="footnote">Verglas en mm et franchissement des 5 cm : non déterminables si le fournisseur ne les chiffre pas. Fonte et tassement non modélisés ici.</p>';
 $('official').innerHTML=html;
 $('hourly').innerHTML=(s?.hourly||[]).filter(h=>Date.parse(h.time)>=Date.now()-3600000).map(h=>'<tr><td>'+local(h.time)+'</td><td>'+esc(h.condition)+'</td><td>'+n(h.temp)+' °C</td><td>'+n(h.wind)+' / '+n(h.gust)+' km/h</td></tr>').join('')||'<tr><td colspan="4">Aucune prévision horaire actuelle disponible.</td></tr>';
}
function renderSources(){
 $('source-cards').innerHTML=state.sources.map(s=>'<article class="panel"><div class="section-heading"><h2>'+esc(s.name)+'</h2><span class="tag '+(stale(s)?'amber':'green')+'">'+(stale(s)?s.status==='stale'?'Anciennes données':'Non disponible':'Données actuelles')+'</span></div><span class="meta">Consultée : '+local(s.fetched_at)+'</span><span class="meta">Émise : '+local(s.issued_at)+'</span><p>'+esc(s.error||s.note||'')+'</p><a href="'+esc(s.url)+'" target="_blank" rel="noopener">Voir la prévision originale ↗</a></article>').join('');
}
function renderWinter(){
 const rows=state.climate.records,months={};
 for(const r of rows){const m=r.date.slice(0,7);if(!months[m])months[m]={total:0,count:0};if(r.snow_cm!=null){months[m].total+=r.snow_cm;months[m].count++}}
 const max=Math.max(1,...Object.values(months).map(m=>m.total));
 $('monthly').innerHTML=Object.entries(months).map(([m,v])=>'<div class="month-row"><span>'+esc(new Intl.DateTimeFormat('fr-CA',{month:'long',timeZone:'America/Toronto'}).format(new Date(m+'-15T12:00:00Z')))+'</span><div class="bar"><span style="width:'+Math.max(v.total?2:0,v.total/max*100)+'%"></span></div><strong>'+n(v.total)+' cm</strong></div>').join('')||'<p class="empty">Les relevés seront ajoutés dès leur publication.</p>';
 const chosen=$('month-filter').value;$('month-filter').innerHTML='<option value="all">Tous les mois</option>'+Object.keys(months).map(m=>'<option value="'+m+'">'+m+'</option>').join('');if([...$('month-filter').options].some(o=>o.value===chosen))$('month-filter').value=chosen;
 renderWinterRows();
}
function renderWinterRows(){if(!state)return;const month=$('month-filter').value;const rows=state.climate.records.filter(r=>month==='all'||r.date.startsWith(month)).slice().reverse();$('winter-rows').innerHTML=rows.map(r=>'<tr><td>'+esc(r.date)+'</td><td>'+n(r.snow_cm)+(r.snow_cm!=null?' cm':'')+'</td><td>'+n(r.rain_mm)+(r.rain_mm!=null?' mm':'')+'</td><td>'+n(r.depth_cm)+(r.depth_cm!=null?' cm':'')+'</td><td>'+esc(r.snow_cm==null?'Non disponible':r.snow_flag||'Valeur publiée')+'</td></tr>').join('')||'<tr><td colspan="5">Aucun relevé disponible.</td></tr>'}
function csv(){if(!state)return;const lines=['Date;Neige_cm;Pluie_mm;Neige_au_sol_cm;Indicateur;Source',...state.climate.records.map(r=>[r.date,r.snow_cm??'',r.rain_mm??'',r.depth_cm??'',r.snow_flag,r.source].map(x=>'"'+String(x).replaceAll('"','""')+'"').join(';'))];const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Saint-Prosper-hiver-'+state.climate.season+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function tab(name){document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!==name);document.querySelectorAll('[data-tab]').forEach(e=>{e.classList.toggle('active',e.dataset.tab===name);e.setAttribute('aria-current',e.dataset.tab===name?'page':'false')});if(name==='radar'){initRadar();setTimeout(()=>map?.invalidateSize(),100)}}
const GEOMET='https://geo.weather.gc.ca/geomet',IEM='https://mesonet.agron.iastate.edu';
const RADAR_SETS={
 RADAR_1KM_RRAI:{obs:'RADAR_1KM_RRAI',extrap:'Radar_1km_RainPrecipRate-Extrapolation',cover:'RADAR_COVERAGE_RRAI.INV',model:'HRDPS.CONTINENTAL_RT'},
 RADAR_1KM_RSNO:{obs:'RADAR_1KM_RSNO',extrap:'Radar_1km_SnowPrecipRate-Extrapolation',cover:'RADAR_COVERAGE_RSNO.INV',model:'HRDPS.CONTINENTAL_RT'},
 Radar_1km_SfcPrecipType:{obs:'Radar_1km_SfcPrecipType',extrap:null,cover:'RADAR_COVERAGE_RRAI.INV',model:null}};
let frames=[],nexradScans=[],layersOn={},capsCache={};
function isoZ(t){return new Date(t).toISOString().replace('.000Z','Z')}
async function layerTimes(name){
 if(capsCache[name]&&Date.now()-capsCache[name].at<240000)return capsCache[name];
 const r=await fetch(GEOMET+'?service=WMS&version=1.3.0&request=GetCapabilities&layer='+name,{cache:'no-store'});if(!r.ok)throw Error('Radar non disponible');
 const xml=new DOMParser().parseFromString(await r.text(),'text/xml'),layer=[...xml.getElementsByTagName('Layer')].find(el=>[...el.children].some(c=>c.localName==='Name'&&c.textContent===name));
 const dims=layer?[...layer.getElementsByTagName('Dimension')]:[],dim=dims.find(el=>el.getAttribute('name')==='time'),ref=dims.find(el=>el.getAttribute('name')==='reference_time');if(!dim)throw Error('Heures non disponibles pour '+name);
 const parts=dim.textContent.trim().split('/');let times=[];
 if(parts.length===3){const start=Date.parse(parts[0]),end=Date.parse(parts[1]),m=/PT(?:(\d+)H)?(?:(\d+)M)?/.exec(parts[2]),step=m?((+m[1]||0)*3600+(+m[2]||0)*60)*1000:360000;for(let t=start;t<=end&&step;t+=step)times.push(t)}
 else times=dim.textContent.trim().split(',').map(t=>Date.parse(t.trim()));
 return capsCache[name]={times,ref:ref?.getAttribute('default')||null,at:Date.now()};
}
async function loadNexrad(){
 const end=new Date(),start=new Date(end-3.2*3600000),f=d=>d.toISOString().slice(0,16)+'Z';
 const r=await fetch(IEM+'/json/radar.py?operation=list&radar=CBW&product=N0B&start='+f(start)+'&end='+f(end));if(!r.ok)throw Error('Radar NOAA non disponible');
 nexradScans=((await r.json()).scans||[]).map(s=>Date.parse(s.ts));
}
async function radarCapabilities(){
 const set=RADAR_SETS[radarLayer],obs=await layerTimes(set.obs);
 const last=obs.times.at(-1);frames=obs.times.filter(t=>t>=last-3*3600000).map(t=>({time:t,kind:'obs',layer:set.obs}));
 if(set.extrap){try{const ex=await layerTimes(set.extrap);ex.times.filter(t=>t>last).forEach(t=>frames.push({time:t,kind:'extrap',layer:set.extrap}))}catch{}}
 if(set.model){try{const md=await layerTimes(set.model),after=frames.at(-1).time;md.times.filter(t=>t>after&&t<=after+6*3600000).forEach(t=>frames.push({time:t,kind:'model',layer:set.model,ref:md.ref}))}catch{}}
 if($('radar-compare').checked){try{await loadNexrad()}catch(e){$('radar-error').textContent=e.message}}
 const idx=frames.findIndex(f=>f.time===last);$('radar-time').max=frames.length-1;$('radar-time').value=idx;$('radar-error').textContent='';
 if(Date.now()-last>30*60000)$('radar-error').textContent='Dernière image radar âgée de plus de 30 minutes.';
 showRadar();
}
function setLayer(key,layer){if(layersOn[key])map.removeLayer(layersOn[key]);layersOn[key]=layer;if(layer)layer.addTo(map)}
function nearestScan(t){let best=null;for(const s of nexradScans)if(Math.abs(s-t)<=7*60000&&(best==null||Math.abs(s-t)<Math.abs(best-t)))best=s;return best}
function showRadar(){
 if(!map||!frames.length)return;const f=frames[+$('radar-time').value],compare=$('radar-compare').checked,mix=+$('radar-mix').value/100;
 const lastObs=frames.filter(x=>x.kind==='obs').at(-1).time,eccOpacity=compare?1-mix:.75;
 const opts={layers:f.layer,format:'image/png',transparent:true,version:'1.3.0',time:isoZ(f.time),opacity:eccOpacity,attribution:'Radar © Environnement et Changement climatique Canada'};if(f.ref)opts.dim_reference_time=f.ref;
 const main=L.tileLayer.wms(GEOMET,opts);main.on('tileerror',()=>{$('radar-error').textContent='Une image n’a pas chargé. Vérifie la carte officielle.'});setLayer('main',main);
 const set=RADAR_SETS[radarLayer];
 setLayer('cover',$('radar-cover').checked&&set.cover?L.tileLayer.wms(GEOMET,{layers:set.cover,format:'image/png',transparent:true,version:'1.3.0',time:isoZ(f.kind==='obs'?f.time:lastObs),opacity:.55}):null);
 let noaa='';
 if(compare&&f.kind==='obs'){const s=nearestScan(f.time);if(s){const d=new Date(s),ts=d.toISOString().slice(0,16).replace(/[-T:]/g,'');setLayer('nexrad',L.tileLayer(IEM+'/cache/tile.py/1.0.0/ridge::CBW-N0B-'+ts+'/{z}/{x}/{y}.png',{opacity:mix,maxNativeZoom:10,attribution:'NEXRAD KCBW © NOAA/NWS · IEM'}));noaa=' · NOAA '+local(s,{month:undefined,day:undefined})}else{setLayer('nexrad',null);noaa=' · NOAA : pas d’image à cette heure'}}
 else{setLayer('nexrad',null);if(compare)noaa=' · NOAA : pas de prévision'}
 const label=f.kind==='obs'?'Observé':f.kind==='extrap'?'Prévision radar (extrapolation)':'Modèle HRDPS';
 $('radar-date').textContent=label+' · '+local(f.time)+noaa;$('radar-date').className=f.kind==='obs'?'':'forecast';
 $('radar-legend').src=GEOMET+'?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image/png&layer='+f.layer;
}
async function initRadar(){if(map)return;if(typeof L==='undefined'){$('radar-error').textContent='Carte non disponible. Ouvre le radar officiel avec le lien ci-dessous.';return}map=L.map('map').setView([46.214,-70.486],8);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:14,attribution:'Fond © Esri, HERE, Garmin, USGS, contributeurs'}).addTo(map);L.circleMarker([46.214,-70.486],{radius:7,color:'#fff',weight:2,fillColor:'#ffc766',fillOpacity:1}).addTo(map).bindPopup('Saint-Prosper · seuil de 5 cm');L.circleMarker([46.039,-67.806],{radius:5,color:'#fff',weight:1,fillColor:'#8ac7eb',fillOpacity:1}).addTo(map).bindPopup('Radar NOAA KCBW · Caribou (Maine)');try{await radarCapabilities()}catch(e){$('radar-error').textContent=e.message+' · consulter le lien officiel.'}}
function stopRadar(){clearInterval(timer);timer=null;$('radar-play').textContent='▶ Animer'}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{stopRadar();tab(b.dataset.tab)}));
$('refresh').addEventListener('click',load);$('month-filter').addEventListener('change',renderWinterRows);$('csv').addEventListener('click',csv);
$('radar-layer').addEventListener('change',async e=>{stopRadar();radarLayer=e.target.value;try{await radarCapabilities()}catch(err){$('radar-error').textContent=err.message}});
$('radar-time').addEventListener('input',()=>{stopRadar();showRadar()});$('radar-mix').addEventListener('input',showRadar);$('radar-cover').addEventListener('change',showRadar);$('radar-compare').addEventListener('change',async()=>{$('radar-mix-wrap').hidden=!$('radar-compare').checked;if($('radar-compare').checked){try{await loadNexrad()}catch(e){$('radar-error').textContent=e.message}}showRadar()});$('radar-home').addEventListener('click',()=>map?.setView([46.214,-70.486],8));
$('radar-play').addEventListener('click',()=>{if(timer){stopRadar();return}if(!frames.length)return;$('radar-play').textContent='Ⅱ Pause';timer=setInterval(()=>{$('radar-time').value=(+$('radar-time').value+1)%frames.length;showRadar()},1100)});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopRadar();else load()});setInterval(()=>{if(!document.hidden){load();if(map&&!$('radar').hidden)radarCapabilities().catch(()=>{})}},300000);
if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});
function relTable(rows){
 if(!rows?.length)return '<p class="muted">Pas encore assez de jours comparés.</p>';
 const cm=v=>v==null?'—':n(v)+' cm',sg=v=>v==null?'—':(v>0?'+':'')+n(v)+' cm';
 return '<div class="table-scroll"><table class="rel"><thead><tr><th>Source</th><th>Écart par épisode</th><th>Biais</th><th>Écart précip.</th><th>Tempêtes 5 cm+ vues</th><th>Manquées</th><th>Fausses alertes</th><th>Épisodes</th></tr></thead><tbody>'+rows.map((r,i)=>'<tr'+(i===0?' class="best"':'')+'><td>'+(i===0?'★ ':'')+esc(r.nom)+'</td><td>'+cm(r.ecart_moyen_cm)+'</td><td>'+sg(r.biais_cm)+'</td><td>'+(r.ecart_precip_mm==null?'—':n(r.ecart_precip_mm)+' mm')+'</td><td>'+r.tempetes.detectees+'</td><td>'+r.tempetes.manquees+'</td><td>'+r.tempetes.fausses_alertes+'</td><td>'+(r.episodes??'—')+'</td></tr>').join('')+'</tbody></table></div>';
}
function renderReliability(){
 const s=state.scores;if(!s){$('reliability-method').textContent='Le tableau apparaîtra après le prochain passage du robot.';return}
 $('reliability-method').textContent=s.methode+' Biais : + = prévoit plus de neige que mesuré, − = moins.';
 const hist=s.historique||[],live=s.en_direct||[];
 const per=r=>r?.periode?' ('+dateOnly(r.periode[0])+' – '+dateOnly(r.periode[1])+')':'';
 $('reliability').innerHTML='<h3>Hiver dernier, prévision de la veille'+per(hist[0])+'</h3>'+relTable(hist)+'<p class="footnote">Seuls les modèles dont les prévisions passées sont archivées publiquement (européens et américain) peuvent être évalués sur l’hiver dernier.</p><h3>Cet hiver, toutes les sources suivies'+per(live[0])+'</h3>'+relTable(live)+'<p class="footnote">Se remplit chaque jour à partir des archives du robot : MétéoMédia, Weather Underground, modèles canadiens, européen, américain, MET Norway et le consensus du plan.</p>';
 if(hist[0])$('reliability-tag').textContent='Meilleur hiver dernier : '+hist[0].nom;
}
const hhmm=v=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',hour:'numeric',minute:'2-digit'}).format(new Date(v)):'—';
const dayOf=v=>new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'long',day:'numeric',month:'long'}).format(new Date(v));
function between(a,b){if(!a||hhmm(a)===hhmm(b))return '';if(!b)return ' (dès '+hhmm(a)+' selon le modèle le plus enneigé; jamais selon le moins enneigé)';return ' (entre '+hhmm(a)+' et '+hhmm(b)+' selon les modèles)'}
function renderPlan(){
 const models=state.models||[],ok=models.filter(m=>m.status==='ok');
 $('plan-models').textContent=ok.length+' / '+models.length+' modèles';$('plan-models').className='tag '+(ok.length>=2?'green':'amber');
 $('model-list').innerHTML=models.map(m=>'<span class="tag '+(m.status==='ok'?'':'amber')+'" title="'+esc(m.error||m.note||'')+'">'+esc(m.name)+(m.status==='ok'?'':' · indisponible')+'</span>').join(' ');
 const plans=state.plan||[];
 if(!models.length)$('plan').innerHTML='<p class="muted">Le plan de sortie apparaîtra après la prochaine collecte du robot.</p>';
 else if(!plans.length)$('plan').innerHTML='<div class="plan-card calm"><strong>Aucune sortie prévue</strong><p class="muted">Les modèles ne prévoient pas d’épisode de neige approchant '+(state.plan_config?.seuil_cm||5)+' cm dans les 72 prochaines heures.</p></div>';
 else $('plan').innerHTML=plans.map(p=>{
  const go=p.statut!=='sous_seuil',tag=p.statut==='sortie'?'SORTIE PRÉVUE':p.statut==='possible'?'SORTIE POSSIBLE':'SOUS LE SEUIL';
  let html='<div class="plan-card '+(p.statut==='sortie'?'go':p.statut==='possible'?'maybe':'calm')+'"><div class="plan-top"><span class="tag '+(p.statut==='sortie'?'amber':'')+'">'+tag+'</span><span class="muted">Confiance '+esc(p.confiance.toLowerCase())+' · '+p.modeles+' modèle'+(p.modeles>1?'s':'')+'</span></div>';
  if(go){html+='<h3>'+esc(dayOf(p.depart))+'</h3><div class="plan-times"><div><label>Départ</label><strong>'+hhmm(p.depart)+'</strong></div>'+(p.echeance?'<div><label>Propre pour</label><strong>'+hhmm(p.echeance)+'</strong></div>':'<div><label>Fin de tournée</label><strong>≈ '+hhmm(p.fin_tournee)+'</strong></div>')+'<div><label>Fin de la tempête</label><strong>≈ '+hhmm(p.fin)+'</strong></div>'+(p.final?'<div><label>'+(p.final.type==='deuxieme_tournee'?'2e tournée':'Nettoyage final')+'</label><strong>'+hhmm(p.final.heure)+'</strong></div>':'')+'</div>';
   html+='<ul class="plan-facts"><li>'+n(p.plan_config_seuil||state.plan_config?.seuil_cm||5)+' cm atteints vers <b>'+hhmm(p.seuil_atteint||p.seuil_fourchette[0])+'</b>'+esc(between(p.seuil_fourchette[0],p.seuil_fourchette[1]))+'</li><li>Neige de l’épisode : <b>≈ '+n(p.total_cm)+' cm</b> (fourchette '+n(p.fourchette_cm[0])+'–'+n(p.fourchette_cm[1])+' cm), du '+esc(dayOf(p.debut))+' '+hhmm(p.debut)+' au '+(dayOf(p.fin)===dayOf(p.debut)?'':esc(dayOf(p.fin))+' ')+hhmm(p.fin)+'</li>'+(p.ensemble?'<li>Ensemble européen (51 versions du modèle) : <b>'+p.ensemble.prob_5cm+' %</b> de chances de 5 cm ou plus ce jour-là · médiane '+n(p.ensemble.p50_cm)+' cm, de '+n(p.ensemble.p10_cm)+' à '+n(p.ensemble.p90_cm)+' cm (10–90 %)</li>':'')+'<li>Tournée de <b>'+n(p.duree_h)+' h</b> par machine'+(p.neige_a_echeance_cm!=null?' pour ≈ '+n(p.neige_a_echeance_cm)+' cm tombés à l’échéance':'')+'</li>'+(p.final?'<li>'+(p.final.type==='deuxieme_tournee'?'2e tournée complète':'Nettoyage final')+' : ≈ '+n(p.final.neige_cm)+' cm tombés après le départ'+(p.final.duree_h?' · '+n(p.final.duree_h)+' h':'')+'</li>':'<li>Pas de nettoyage final prévu : la neige cesse avant ou peu après le départ.</li>')+'</ul>';}
  else html+='<p>'+esc(p.resume)+'</p>';
  if(p.notes?.length)html+='<ul class="plan-notes">'+p.notes.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>';
  return html+'</div>'}).join('');
 const hours=(state.hourly_snow||[]).filter(h=>Date.parse(h.time)+3600000>Date.now()).slice(0,48);
 if(!hours.length){$('timeline').innerHTML='<p class="muted">Aucune série horaire disponible.</p>';return}
 const max=Math.max(1,...hours.map(h=>h.hi)),marks={};
 for(const p of plans){if(p.depart)marks[new Date(p.depart).setMinutes(0,0,0)]='Départ';if(p.final)marks[new Date(p.final.heure).setMinutes(0,0,0)]=p.final.type==='deuxieme_tournee'?'2e tournée':'Final'}
 $('timeline').innerHTML=hours.map((h,i)=>{const t=Date.parse(h.time),hr=+new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',hour:'numeric',hourCycle:'h23'}).formatToParts(new Date(t)).find(x=>x.type==='hour').value,mark=marks[t];
  return '<div class="tl-col'+(hr===0?' midnight':'')+(mark?' mark':'')+'" title="'+esc(hhmm(h.time)+' · '+n(h.snow_cm)+' cm/h (de '+n(h.lo)+' à '+n(h.hi)+') · '+h.n+' modèles')+'"><div class="tl-bar"><span class="tl-range" style="bottom:'+(h.lo/max*100)+'%;height:'+Math.max(0,(h.hi-h.lo)/max*100)+'%"></span><span class="tl-med" style="height:'+(h.snow_cm/max*100)+'%"></span></div>'+(mark?'<em>'+esc(mark)+'</em>':'')+'<small>'+(hr===0?esc(new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'short'}).format(new Date(t))):hr%3===0?hr+'h':'')+'</small></div>'}).join('');
}
load();
