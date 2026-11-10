'use strict';
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=v=>v==null?'—':new Intl.NumberFormat('fr-CA',{maximumFractionDigits:1}).format(v);
const local=(v,opts={})=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',...opts}).format(new Date(v)):'Non publiée';
const dayLabel=v=>new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'short',month:'short',day:'numeric'}).format(new Date(v+'T12:00:00-05:00'));
const dateOnly=v=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',day:'numeric',month:'short'}).format(new Date(v+'T12:00:00-05:00')):'—';
let state=null,selected=0,map=null,radar=null,radarTimes=[],timer=null,radarLayer='RADAR_1KM_RRAI';
function stale(s){return s.status!=='ok'||(s.issued_at?Date.now()-Date.parse(s.issued_at)>18*3600000:Date.now()-Date.parse(s.fetched_at)>3*3600000)}
function symbol(types){let t=types.join(' ');return /Verglas/.test(t)?'◈':/Pluie \/ neige/.test(t)?'🌨':/Neige/.test(t)?'❄':/Pluie/.test(t)?'🌧':'☁'}
function displayQty(d){if(!d?.snow_cm)return '—';return d.snow_cm[0]===d.snow_cm[1]?n(d.snow_cm[0])+' cm':n(d.snow_cm[0])+'–'+n(d.snow_cm[1])+' cm'}
async function load(){
  $('refresh').disabled=true;
  try{
    const r=await fetch('data/weather.json',{cache:'no-store'});if(!r.ok)throw new Error('Données indisponibles');
    const j=await r.json();if(!Array.isArray(j.sources)||!j.climate)throw new Error('Format de données non reconnu');state=j;
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
  $('status').innerHTML='<div><span class="tag amber">'+label+'</span><h2>'+title+'</h2><p>Seuil opérationnel : 5 cm de nouvelle neige au sol. '+(threshold?'Les cm annoncés concernent la neige tombée; le seuil réel au sol reste à vérifier.':'Les quantités comparables ne permettent pas de confirmer l’atteinte des 5 cm au sol.')+'</p></div>';
  $('days').innerHTML=state.consensus.map((d,i)=>'<button class="day '+(selected===i?'active':'')+'" data-day="'+i+'" aria-pressed="'+(selected===i)+'"><span class="date">'+esc(dayLabel(d.date))+'</span><span class="symbol">'+symbol(d.risks)+'</span><strong>'+n(d.high_mean)+'° <span class="muted">/ '+n(d.low_mean)+'°</span></strong><small>'+d.sources.length+' sources · '+esc(d.confidence)+'</small><small>Neige : '+(d.snow.mean_cm==null?'non chiffrable':n(d.snow.mean_cm)+' cm')+'</small></button>').join('');
  document.querySelectorAll('[data-day]').forEach(b=>b.addEventListener('click',()=>{selected=Number(b.dataset.day);render()}));
  renderComparison();renderOfficial();renderWinter();renderSources();
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
async function radarCapabilities(){
 const r=await fetch('https://geo.weather.gc.ca/geomet?service=WMS&version=1.3.0&request=GetCapabilities&layer='+radarLayer,{cache:'no-store'});if(!r.ok)throw Error('Radar non disponible');const xml=new DOMParser().parseFromString(await r.text(),'text/xml');
 const layers=[...xml.getElementsByTagName('Layer')],layer=layers.find(el=>[...el.children].some(c=>c.localName==='Name'&&c.textContent===radarLayer));
 const dimension=layer&&[...layer.getElementsByTagName('Dimension')].find(el=>el.getAttribute('name')==='time');if(!dimension)throw Error('Heures radar non disponibles');
 const parts=dimension.textContent.trim().split('/');
 if(parts.length===3){const start=Date.parse(parts[0]),end=Date.parse(parts[1]);const match=/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/.exec(parts[2]);const step=match?((+match[1]||0)*3600+(+match[2]||0)*60+(+match[3]||0))*1000:360000;if(!step)throw Error('Pas radar non reconnu');radarTimes=[];for(let t=Math.max(start,end-2*3600000);t<=end;t+=step)radarTimes.push(new Date(t).toISOString().replace('.000Z','Z'))}
 else radarTimes=dimension.textContent.trim().split(',').map(t=>t.trim());
 if(!radarTimes.length)throw Error('Aucune image radar datée');$('radar-time').max=radarTimes.length-1;$('radar-time').value=radarTimes.length-1;$('radar-error').textContent='';showRadar();
}
function showRadar(){if(!map||!radarTimes.length)return;const time=radarTimes[+$('radar-time').value];if(radar)map.removeLayer(radar);radar=L.tileLayer.wms('https://geo.weather.gc.ca/geomet',{layers:radarLayer,format:'image/png',transparent:true,version:'1.3.0',time,opacity:.75,attribution:'Radar © Environnement et Changement climatique Canada'}).addTo(map);radar.on('tileerror',()=>{$('radar-error').textContent='Une image radar n’a pas chargé. Vérifie la carte officielle.'});$('radar-date').textContent=local(time);if(Date.now()-Date.parse(radarTimes.at(-1))>30*60000)$('radar-error').textContent='Dernière image radar âgée de plus de 30 minutes.';$('radar-legend').src='https://geo.weather.gc.ca/geomet?service=WMS&version=1.3.0&request=GetLegendGraphic&format=image/png&layer='+radarLayer;}
async function initRadar(){if(map)return;if(typeof L==='undefined'){$('radar-error').textContent='Carte non disponible. Ouvre le radar officiel avec le lien ci-dessous.';return}map=L.map('map').setView([46.214,-70.486],8);L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:14,attribution:'Fond © Esri, HERE, Garmin, USGS, contributeurs'}).addTo(map);L.circleMarker([46.214,-70.486],{radius:7,color:'#fff',weight:2,fillColor:'#ffc766',fillOpacity:1}).addTo(map).bindPopup('Saint-Prosper · seuil de 5 cm');try{await radarCapabilities()}catch(e){$('radar-error').textContent=e.message+' · consulter le lien officiel.'}}
function stopRadar(){clearInterval(timer);timer=null;$('radar-play').textContent='▶ Animer'}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{stopRadar();tab(b.dataset.tab)}));
$('refresh').addEventListener('click',load);$('month-filter').addEventListener('change',renderWinterRows);$('csv').addEventListener('click',csv);
$('radar-layer').addEventListener('change',async e=>{stopRadar();radarLayer=e.target.value;try{await radarCapabilities()}catch(err){$('radar-error').textContent=err.message}});
$('radar-time').addEventListener('input',()=>{stopRadar();showRadar()});$('radar-home').addEventListener('click',()=>map?.setView([46.214,-70.486],8));
$('radar-play').addEventListener('click',()=>{if(timer){stopRadar();return}if(!radarTimes.length)return;$('radar-play').textContent='Ⅱ Pause';timer=setInterval(()=>{$('radar-time').value=(+$('radar-time').value+1)%radarTimes.length;showRadar()},1100)});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopRadar();else load()});setInterval(()=>{if(!document.hidden){load();if(map&&!$('radar').hidden)radarCapabilities().catch(()=>{})}},300000);
if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});
load();
