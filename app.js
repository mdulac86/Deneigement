'use strict';
const $=id=>document.getElementById(id), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=v=>v==null?'—':new Intl.NumberFormat('fr-CA',{maximumFractionDigits:1}).format(v);
const local=(v,opts={})=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',...opts}).format(new Date(v)):'Non publiée';
const dayLabel=v=>new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'short',month:'short',day:'numeric'}).format(new Date(v+'T12:00:00-05:00'));
const dateOnly=v=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',day:'numeric',month:'short'}).format(new Date(v+'T12:00:00-05:00')):'—';
let state=null,selected=0,map=null,timer=null,radarLayer='RADAR_1KM_RRAI';
function working(s){return s.status==='ok'||(s.status==='stale'&&Date.now()-Date.parse(s.fetched_at)<24*3600000)}
function stale(s){return s.status!=='ok'||(s.issued_at?Date.now()-Date.parse(s.issued_at)>18*3600000:Date.now()-Date.parse(s.fetched_at)>(s.relay?7:3)*3600000)}
const ICONS={"ice": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><path d=\"M14 36l4 6M22 36l4 6M30 36l4 6\" stroke=\"#FF6B35\" stroke-width=\"2.5\" stroke-linecap=\"round\"/></svg>", "mix": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><g stroke=\"#7CC4F0\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M17 36v8M13.5 38l7 4M13.5 42l7-4\"/></g><path d=\"M30 37l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/></svg>", "snow": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><g stroke=\"#7CC4F0\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M16 36v8M12.5 38l7 4M12.5 42l7-4\"/></g><g stroke=\"#7CC4F0\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M31 36v8M27.5 38l7 4M27.5 42l7-4\"/></g></svg>", "rain": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/><path d=\"M16 37l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/><path d=\"M24 39l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/><path d=\"M32 37l-2.5 5a2.6 2.6 0 0 0 5 0z\" fill=\"#7CC4F0\"/></svg>", "cloud": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><circle cx=\"16\" cy=\"17\" r=\"7\" fill=\"#FFB81C\"/><path d=\"M14 30h20a7 7 0 0 0 0-14 10 10 0 0 0-19-2 7 7 0 0 0-1 16z\" fill=\"#D4D4D8\"/></svg>", "sun": "<svg viewBox=\"0 0 48 48\" aria-hidden=\"true\"><circle cx=\"24\" cy=\"24\" r=\"9\" fill=\"#FFB81C\"/><g stroke=\"#FFB81C\" stroke-width=\"3\" stroke-linecap=\"round\"><path d=\"M24 6v6M24 36v6M6 24h6M36 24h6M11 11l4 4M33 33l4 4M37 11l-4 4M15 33l-4 4\"/></g></svg>"};
function riskOf(text){const t=String(text||'').toLowerCase();return /vergla|grésil|freezing|ice pellet/.test(t)?'Verglas / grésil':(/neige/.test(t)&&/pluie/.test(t))||/mixte|sleet|rain\/snow/.test(t)?'Pluie / neige':/neige|flocon|snow|flurr/.test(t)?'Neige':/pluie|averse|bruine|rain|drizzle|shower/.test(t)?'Pluie':/dégag|ensoleill|soleil|sunny|clear/.test(t)?'Soleil':'Nuage'}
function symbol(types){if(types.includes('Soleil'))return ICONS.sun;let t=types.join(' ');return /Verglas/.test(t)?ICONS.ice:/Pluie \/ neige/.test(t)?ICONS.mix:/Neige/.test(t)?ICONS.snow:/Pluie/.test(t)?ICONS.rain:ICONS.cloud}
function displayQty(d){if(!d?.snow_cm)return '—';return d.snow_cm[0]===d.snow_cm[1]?n(d.snow_cm[0])+' cm':n(d.snow_cm[0])+'–'+n(d.snow_cm[1])+' cm'}
async function load(){
  $('refresh').disabled=true;
  try{
    const r=await fetch('data/weather.json',{cache:'no-store'});if(!r.ok)throw new Error('Données indisponibles');
    const j=await r.json();if(!Array.isArray(j.sources)||!j.climate)throw new Error('Format de données non reconnu');state=j;
    try{const s=await fetch('data/verification/scores.json',{cache:'no-store'});if(s.ok)j.scores=await s.json()}catch{}
    // Onglet Mon hiver : hiver dernier (relevés Climat Québec) et normale à pareille date (15 hivers récents).
    const yPrev=+(j.climate.start||'').slice(0,4)-1,get=u=>fetch(u,{cache:'no-store'}).then(x=>x.ok?x.json():null).catch(()=>null);
    [j.precedent,j.normale_date]=await Promise.all([yPrev?get('data/season-'+yPrev+'.json'):null,get('data/normale-par-date.json')]);
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
  const active=state.sources.filter(s=>!stale(s)),models=(state.models||[]).filter(m=>m.status==='ok');$('source-count').textContent=active.length+models.length;$('source-count-note').textContent=active.length+' sites et bulletins + '+models.length+' modèles à jour';
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
  const watch=ice||mixed||snow||threshold;
  $('status-line').className='status-line '+(hasOfficial?'alert':watch?'watch':'calm');
  $('status-line').innerHTML='<span class="tag '+(hasOfficial?'red':watch?'amber':'green')+'">'+(hasOfficial?'Alerte':watch?'À surveiller':'Calme')+'</span><span>'+esc(title)+'</span>';
  $('updated-at').textContent='Mis à jour à '+hhmm(state.updated_at);
  try{renderQuick()}catch(err){console.warn('aperçu',err)}
  $('status').className='signal '+(hasOfficial?'alert':ice||mixed||snow||threshold?'watch':'calm');$('status').innerHTML='<div><span class="tag '+(hasOfficial?'':ice||mixed||snow||threshold?'amber':'green')+'">'+label+'</span><h2>'+title+'</h2><p>Seuil opérationnel : 5 cm de nouvelle neige au sol. '+(threshold?'Les cm annoncés concernent la neige tombée; le seuil réel au sol reste à vérifier.':'Les quantités comparables ne permettent pas de confirmer l’atteinte des 5 cm au sol.')+'</p></div>';
  let ch=null;try{ch=chantiers()}catch(err){console.warn('chantiers',err)}
  try{const sm=summary72();if(ch)sm.text+=(ch.pave?'\nPaver : '+ch.pave:'')+'\nExcavation : '+ch.exc;
   $('status').insertAdjacentHTML('beforeend',sm.html);$('status-chantier').innerHTML=sm.html;
   document.querySelectorAll('.copy72').forEach(b=>b.onclick=async e=>{try{await navigator.clipboard.writeText(sm.text);e.target.textContent='Copié ✓'}catch{if(navigator.share)navigator.share({text:sm.text})}})}catch(err){console.warn('résumé 72 h',err)}
  try{erabliere()}catch(err){console.warn('érablière',err)}
  $('days').innerHTML=state.consensus.map((d,i)=>'<button class="day '+(selected===i?'active':'')+(d.tendance?' trend':'')+'" data-day="'+i+'" aria-pressed="'+(selected===i)+'"><span class="date">'+esc(dayLabel(d.date))+'</span><span class="symbol">'+symbol(d.risks)+'</span><strong>'+n(d.high_mean)+'° <span class="muted">/ '+n(d.low_mean)+'°</span></strong><small>'+(d.tendance?'Tendance · modèles':d.sources.length+' sources · '+esc(d.confidence))+'</small>'+(d.pop?'<small class="pop'+(d.pop.value>=60?' hi':'')+'" title="Probabilité de précipitations · '+esc(d.pop.sources.join(', '))+'">💧 '+d.pop.value+' %</small>':'')+'<small>Neige : '+(d.snow.mean_cm!=null?n(d.snow.mean_cm)+' cm':d.model_snow?'≈ '+n(d.model_snow.median_cm)+' cm':'non chiffrable')+'</small>'+(d.ensemble?'<small class="'+(d.ensemble.prob_5cm>=30?'ens-high':'')+'">5 cm+ : '+d.ensemble.prob_5cm+' % (ensemble)</small>':'')+(d.nbm&&d.nbm.p_2_5cm>0?'<small class="'+(d.nbm.p_5cm>=30?'ens-high':'')+'" title="Plus forte probabilité sur une tranche de 6 h · NOAA NBM">5 cm+ en 6 h : '+d.nbm.p_5cm+' % (NBM)</small>':'')+(d.verglas_hrrr_h?'<small class="'+(d.verglas_hrrr_confirme?'ens-high':'')+'" title="Heures de pluie verglaçante prévues par le modèle HRRR">🧊 Verglas : '+d.verglas_hrrr_h+' h (HRRR'+(d.verglas_hrrr_confirme?'':', à confirmer')+')</small>':'')+(d.risques_a_confirmer?.length?'<small class="muted" title="Annoncé par une seule source pas encore assez fiable : affiché, sans alerte">À confirmer : '+esc(d.risques_a_confirmer.map(x=>x.risque).join(', '))+'</small>':'')+((d.risks||[]).some(r=>/Poudrerie|Glace \(vent\)/.test(r))?'<small class="ens-high">💨 '+((d.risks||[]).includes('Poudrerie')?'Poudrerie':'Glace (vent)')+' · '+n(d.rafales_kmh)+' km/h</small>':d.rafales_kmh>=40?'<small>💨 Rafales '+n(d.rafales_kmh)+' km/h</small>':'')+'</button>').join('');
  document.querySelectorAll('[data-day]').forEach(b=>b.addEventListener('click',()=>{selected=Number(b.dataset.day);render()}));
  renderPlan();try{renderNbm()}catch(err){console.warn('NBM',err)}try{renderRoutes()}catch(err){console.warn('routes',err)}try{renderTransport()}catch(err){console.warn('transport',err)}try{renderMoto()}catch(err){console.warn('motoneige',err)}renderDepth();renderComparison();renderOfficial();renderWinter();renderSources();renderReliability();
  $('previous').textContent=state.previous_at?'Depuis '+local(state.previous_at):'État de référence';$('changes').innerHTML=state.changes.map(c=>'<li>'+esc(c.text)+'</li>').join('');
}
function renderComparison(){
  const d=state.consensus[selected], q=d.snow;$('compare-title').textContent=dayLabel(d.date);$('compare-confidence').textContent='Confiance '+d.confidence.toLowerCase();
  $('mean-snow').textContent=q.mean_cm==null?'Indéterminée':n(q.mean_cm)+' cm';$('mean-note').textContent=q.count+' sources avec cm et périodes compatibles · '+dateOnly(d.date);
  let summary=q.mean_cm==null?'<b>Moyenne de neige indisponible</b><br><span class="muted">Moins de 2 sources avec une quantité en cm pour la même période. Les bulletins restent consultables ci-contre.</span>':'<b>Moyenne '+n(q.mean_cm)+' cm</b> · médiane '+n(q.median_cm)+' cm<br>Fourchette '+n(q.min_cm)+'–'+n(q.max_cm)+' cm · '+q.count+' sources';
  let html='<div class="summary-strip">'+summary+'</div>';
  if(d.high_range)html+='<p class="footnote">Maximum : moyenne '+n(d.high_mean)+' °C · sources de '+n(d.high_range[0])+' à '+n(d.high_range[1])+' °C. '+esc(d.confidence_reason)+'</p>';
  for(const source of state.sources.filter(working)){const row=d.sources.find(x=>x.source===source.id);html+='<div class="compare-row"><div class="source-name"><a href="'+esc(source.url)+'" target="_blank" rel="noopener">'+esc(source.name)+' ↗</a><small>'+(!row||stale(source)?'Hors consensus':'Consultée '+local(source.fetched_at,{month:undefined,day:undefined}))+'</small></div><div>'+esc(row?.risk||'Données indisponibles')+'<small>'+n(row?.high)+'° / '+n(row?.low)+'°</small></div><div class="qty">'+displayQty(row)+'<small>neige</small></div></div>'}
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
 $('hourly').innerHTML=(s?.hourly||[]).filter(h=>Date.parse(h.time)>=Date.now()-3600000).map(h=>'<tr><td>'+hhmm(h.time)+'</td><td class="cond"><span class="ico">'+symbol([riskOf(h.condition)])+'</span>'+esc(h.condition)+'</td><td>'+(h.pop!=null?'<span class="pop'+(h.pop>=60?' hi':'')+'">'+h.pop+' %</span>':'<span class="muted">—</span>')+'</td><td>'+n(h.temp)+' °C</td><td>'+n(h.wind)+' / '+n(h.gust)+' km/h</td></tr>').join('')||'<tr><td colspan="5">Aucune prévision horaire actuelle disponible.</td></tr>';
}
function renderSources(){
 $('source-cards').innerHTML=state.sources.filter(working).map(s=>'<article class="panel"><div class="section-heading"><h2>'+esc(s.name)+'</h2><span class="tag '+(stale(s)?'amber':'green')+'">'+(stale(s)?s.status==='stale'?'Anciennes données':'Non disponible':'Données actuelles')+'</span></div><span class="meta">Consultée : '+local(s.fetched_at)+'</span><span class="meta">Émise : '+local(s.issued_at)+'</span><p>'+esc(s.error||s.note||'')+'</p><a href="'+esc(s.url)+'" target="_blank" rel="noopener">Voir la prévision originale ↗</a></article>').join('');
}
function med(a){if(!a.length)return null;const b=a.slice().sort((x,y)=>x-y),m=b.length>>1;return b.length%2?b[m]:(b[m-1]+b[m])/2}
function summary72(){
 // Résumé des 72 prochaines heures : médiane des modèles horaires qui couvrent toute la période.
 const now=Date.now(),end=now+72*3600e3,ok=(state.models||[]).filter(m=>m.status==='ok'&&(m.hours||[]).some(h=>h.precip_mm!=null));
 const runs=ok.map(m=>m.hours.filter(h=>{const t=Date.parse(h.time);return t>=now-3600e3&&t<end})).filter(h=>h.length&&Date.parse(h[h.length-1].time)>=end-6*3600e3);
 const fmtDay=t=>new Intl.DateTimeFormat('fr-CA',{weekday:'short',day:'numeric',timeZone:'America/Toronto'}).format(t),key=t=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/Toronto'}).format(t);
 const rain=[],snow=[],perHour={},dayRain={};
 for(const hs of runs){let r=0,s=0;const dr={};
  for(const h of hs){const p=h.precip_mm||0,sn=h.snow_cm||0,liq=sn>0?0:p;r+=liq;s+=sn;(perHour[h.time]=perHour[h.time]||[]).push(p);const k=key(Date.parse(h.time));dr[k]=(dr[k]||0)+liq}
  rain.push(r);snow.push(s);for(const k in dr)(dayRain[k]=dayRain[k]||[]).push(dr[k])}
 const hours=Object.entries(perHour).sort().slice(-72),wet=hours.filter(([,v])=>med(v)>=0.2),first=wet[0]?Date.parse(wet[0][0]):null;
 // Jours touchés par la fenêtre : un jour partiel (ex. lundi 0 h-7 h) compte s'il y tombe de la pluie dans la fenêtre.
 const days=(state.consensus||[]).filter(d=>{const a=Date.parse(d.date+'T00:00:00-05:00'),b=a+86400e3,cover=(Math.min(b,end)-Math.max(a,now))/3600e3;return cover>=1&&(cover>=6||med(dayRain[d.date]||[])>=0.2)}).slice(0,4);
 const pops=days.map(d=>d.pop?.value).filter(v=>v!=null),pop=pops.length?Math.max(...pops):null;
 const hi=days.map(d=>d.high_mean).filter(v=>v!=null),lo=days.map(d=>d.low_mean).filter(v=>v!=null),gust=days.map(d=>d.rafales_kmh).filter(v=>v!=null);
 const range=a=>a.length?(Math.round(Math.min(...a))===Math.round(Math.max(...a))?n(Math.round(a[0])):n(Math.round(Math.min(...a)))+' à '+n(Math.round(Math.max(...a))))+' °C':'—';
 const r=med(rain),sn=med(snow),rr=rain.length?' ('+n(Math.min(...rain))+'–'+n(Math.max(...rain))+')':'';
 const dry=hours.length-wet.length;
 const lines=[['💧 Pluie',(r==null?'—':n(Math.round(r*10)/10)+' mm'+rr)+(pop!=null?' @ '+pop+' %':'')],
  ...(sn>=0.5?[['❄ Neige','≈ '+n(Math.round(sn*10)/10)+' cm ('+n(Math.min(...snow))+'–'+n(Math.max(...snow))+')']]:[]),
  ['☀ Jour',range(hi)],['☾ Nuit',range(lo)],
  ...days.filter(d=>d.forte_pluie&&Date.parse(d.forte_pluie.heure)<end).slice(0,1).map(d=>['⛈ Averse',(d.forte_pluie.orage?'orage':'forte pluie')+' '+fmtDay(Date.parse(d.forte_pluie.heure))+' vers '+hhmm(d.forte_pluie.heure)]),
  ['💨 Vent',gust.length?'rafales jusqu’à '+Math.round(Math.max(...gust))+' km/h':'—'],
  ['⏱ Sec',hours.length?'≈ '+dry+' h sans pluie sur '+hours.length+(first?' · première pluie '+fmtDay(first)+' vers '+hhmm(new Date(first).toISOString()):''):'—']];
 const rows=days.map(d=>{const k=d.date,mm=med(dayRain[k]||[]);return '<li><span>'+esc(dayLabel(d.date))+'</span><span class="ico">'+symbol(d.risks)+'</span><b>'+n(Math.round(d.high_mean))+'° / '+n(Math.round(d.low_mean))+'°</b><span>'+(mm!=null?n(Math.round(mm*10)/10)+' mm':'—')+(d.pop?' @ '+d.pop.value+' %':'')+'</span></li>'}).join('');
 const text='Prochaines 72 h (Saint-Prosper)\n'+lines.map(([a,b])=>a.replace(/^\S+ /,'')+' : '+b).join('\n')+'\n'+days.map(d=>dayLabel(d.date)+' : '+n(d.high_mean)+'° / '+n(d.low_mean)+'°'+(d.pop?', '+d.pop.value+' %':'')).join('\n');
 return {html:'<div class="sum72"><div class="sum72-head"><b>Prochaines 72 h</b><button type="button" class="ghost copy72">Copier</button></div><dl>'+lines.map(([a,b])=>'<div><dt>'+a+'</dt><dd>'+b+'</dd></div>').join('')+'</dl><ul>'+rows+'</ul><small class="muted">Médiane de '+runs.length+' modèles (fourchette entre parenthèses) · probabilité : la plus haute des sources.</small></div>',text};
}
function chantiers(){
 // Planification des chantiers (excavation et pavage) : pluie prévue jour par jour (médiane des modèles),
 // heures sèches de jour, et état du sol d'après la pluie des jours précédents (indice qui s'assèche de 15 % par jour).
 const P=$('chantier-panel');if(!P)return;
 const tz='America/Toronto',key=t=>new Intl.DateTimeFormat('en-CA',{timeZone:tz}).format(t),hourOf=t=>+new Intl.DateTimeFormat('en-CA',{timeZone:tz,hour:'numeric',hourCycle:'h23'}).format(t);
 const today=key(Date.now()),ok=(state.models||[]).filter(m=>m.status==='ok'&&(m.hours||[]).some(h=>h.precip_mm!=null));
 // Pluie pondérée par la fiabilité mesurée de chaque modèle pour la pluie (confiance_pluie, recalculée par le robot).
 // Heures sèches : sans NBM ni MétéoMédia, dont les tranches de 6 h réparties sur chaque heure transformeraient une averse en 6 h de pluie.
 const dayModel={},hourVals={},PAR_TRANCHES=['nbm','mm'],wq=(pairs,q=.5)=>{const s=pairs.filter(p=>p[1]>0).sort((a,b)=>a[0]-b[0]);if(!s.length)return null;const tot=s.reduce((a,p)=>a+p[1],0);let c=0;for(const [v,w] of s){c+=w;if(c>=tot*q-1e-9)return v}return s.at(-1)[0]};
 for(const m of ok){const w=m.confiance_pluie?.poids??1,per={};for(const h of m.hours){const t=Date.parse(h.time),k=key(t);if(k<today)continue;const e=per[k]=per[k]||{mm:0,n:0};e.mm+=h.precip_mm||0;e.n++;if(!PAR_TRANCHES.includes(m.id))(hourVals[h.time]=hourVals[h.time]||[]).push([h.precip_mm||0,w])}
  for(const k in per)if(per[k].n>=18||(k===today&&per[k].n>=3))(dayModel[k]=dayModel[k]||[]).push([per[k].mm,w])}
 const dry={},seen={};for(const [t,v] of Object.entries(hourVals)){if(v.length<2)continue;const ts=Date.parse(t),hr=hourOf(ts);if(hr<7||hr>=18||ts<Date.now()-3600e3)continue;const k=key(ts);seen[k]=(seen[k]||0)+1;if(wq(v)<0.1)dry[k]=(dry[k]||0)+1}
 // Pluie observée : relevé Climat Québec de Saint-Prosper si publié, sinon pluviomètre automatique le plus proche.
 const obs={};for(const [d,v] of Object.entries(state.pluie_obs||{}))if(v.h>=18)obs[d]=v.mm;
 for(const r of state.climate?.records||[])if(r.rain_mm!=null)obs[r.date]=r.rain_mm+(r.snow_cm&&r.tmax!=null&&r.tmax>2?r.snow_cm:0);
 let S=0;const start=new Date(Date.now()-14*86400e3);for(let i=0;i<14;i++){const k=key(start.getTime()+i*86400e3);S=S*0.85+(obs[k]||0)}
 const days=(state.consensus||[]).slice(0,10),soilLbl=s=>s<10?['Sec','green']:s<25?['Humide','amber']:['Détrempé','red'];
 const badge=([t,c])=>'<span class="tag '+c+'">'+t+'</span>';
const G=state.gel_sol&&state.gel_sol.gel_m!=null?state.gel_sol:null,proj=Object.fromEntries((G?.projection||[]).map(p=>[p.date,p.gel_m]));
 const gelDay=k=>G?(k<=G.date?G.gel_m:proj[k]??null):null,cm=m=>Math.round(m*100)+' cm';
 const rows=[],goodPave=[],goodExc=[],goodSap=[];
 // Usine d'asphalte ouverte de la mi-mai à la mi-novembre : pas de pavage le reste de l'année.
 const paveOn=k=>{const md=+k.slice(5).replace('-','');return md>=515&&md<=1115},anyPave=days.some(d=>paveOn(d.date));
 $('th-pave').hidden=!anyPave;
 // Saison des sucres (15 févr. au 30 avril) : coulée quand il gèle la nuit (idéal -2 °C et moins) et dégèle le jour (idéal 3 à 10 °C).
 const sugar=false;
 // Gel du sol : indice de gel cumulé (degrés-jours sous 0 °C, qui se perd au dégel).
 let FI=0;for(const r of (state.climate?.records||[]).slice(-21))if(r.tmax!=null&&r.tmin!=null)FI=Math.max(0,FI*0.9-(r.tmax+r.tmin)/2);
 let prevLow=null;
 for(const d of days){const mm=dayModel[d.date]?wq(dayModel[d.date]):null,pop=d.pop?.value??null,hi=d.high_mean,soil=S;
  if(hi!=null&&d.low_mean!=null)FI=Math.max(0,FI*0.9-(hi+d.low_mean)/2);
  const gp=gelDay(d.date),rain=mm??0,dh=seen[d.date]?dry[d.date]||0:null,frozen=gp!=null?gp>=0.3:FI>=15;
  let exc=rain>=10||soil>=40||(rain>=5&&(pop??0)>=70)?['À éviter','red']:rain<3&&(pop??0)<50&&soil<20?['Bon','green']:['Moyen','amber'];
  if(frozen)exc=['Sol gelé','amber'];
  const night=[prevLow,d.low_mean].filter(v=>v!=null),lo=night.length?Math.min(...night):null;prevLow=d.low_mean;
  const sap=hi==null||lo==null?['—','']:lo<=-2&&hi>=3&&hi<=10?['Bonne','green']:lo<=0&&hi>0&&hi<=14?['Possible','amber']:hi<=0?['Gel (rien)','']:['Nuit douce','red'];
  if(sap[1]==='green')goodSap.push(d);
  let pave=!paveOn(d.date)?['Usine fermée','']:rain>=2||(pop??0)>=60||hi==null||hi<5||soil>=40?['À éviter','red']:rain<0.5&&(pop??0)<40&&hi>=10&&soil<25&&(dh==null||dh>=8)?['Bon','green']:['Moyen','amber'];
  if(exc[0]==='Bon')goodExc.push(d);if(pave[0]==='Bon')goodPave.push(d);
  rows.push('<tr'+(d.tendance?' class="trend"':'')+'><td>'+esc(dayLabel(d.date).replace(/ \S+\.?$/,''))+'</td><td class="ico">'+symbol(d.risks)+'</td><td>'+badge(exc)+'</td>'+(anyPave?'<td>'+badge(pave)+'</td>':'')+(sugar?'<td>'+badge(sap)+'</td>':'')+'<td>'+n(hi==null?null:Math.round(hi))+'° / '+n(d.low_mean==null?null:Math.round(d.low_mean))+'°'+(hi>=30?'<br><small class="hot">🥵 Chaleur : apporter de l’eau</small>':'')+'</td><td>'+(mm!=null?n(Math.round(mm*10)/10)+' mm':'—')+(pop!=null?' @ '+pop+' %':'')+(d.forte_pluie?'<br><small class="storm">'+(d.forte_pluie.orage?'⛈ Orage':'🌧 Forte pluie')+' vers '+hhmm(d.forte_pluie.heure)+'</small>':'')+(d.foudre_hrrr&&!d.forte_pluie?.orage?'<br><small class="storm" title="Menace d’éclairs prévue par le modèle HRRR, non confirmée par Environnement Canada">⚡ Foudre possible vers '+hhmm(d.foudre_hrrr)+'</small>':'')+'</td><td>'+(dh!=null?dh+' / '+seen[d.date]+' h':'—')+'</td><td>'+badge(soilLbl(soil))+(gp>=0.05?'<br><small>Gel ≈ '+cm(gp)+'</small>':'')+'</td></tr>');
  S=S*0.85+rain}
 S=0;for(let i=0;i<14;i++){const k=key(start.getTime()+i*86400e3);S=S*0.85+(obs[k]||0)}
 $('chantier-rows').innerHTML=rows.join('');
 const sl=soilLbl(S);$('chantier-sol').className='tag '+sl[1];$('chantier-sol').textContent='Sol aujourd’hui : '+sl[0];
 const list=a=>a.length?a.map(d=>dayLabel(d.date).replace(/ \S+\.?$/,'')).join(', '):'aucun';
 $('chantier-best').innerHTML=(anyPave?'<b>Bons jours pour paver :</b> '+esc(list(goodPave)):'<b>Pavage :</b> usine d’asphalte fermée (ouverte de la mi-mai à la mi-novembre)')+'<br><b>Bons jours pour l’excavation :</b> '+esc(list(goodExc))+(sugar?'<br><b>Bonnes coulées (érablière) :</b> '+esc(list(goodSap)):'')+(G?'<span class="gel-card"><b>Gel dans le sol</b> (MTQ '+esc(G.station)+', '+esc(dateOnly(G.date))+') : <strong>'+(G.gel_m>0?cm(G.gel_m):'aucun')+'</strong>'+(G.degel_m>0?' · dégelé sur '+cm(G.degel_m)+' en surface':'')+(G.normale_m!=null?' · normale à cette date '+cm(G.normale_m):'')+((G.projection||[]).length?' · dans '+G.projection.length+' jours ≈ '+cm(G.projection[G.projection.length-1].gel_m):'')+(G.hiver_passe_max_m!=null?' · hiver passé : '+n(G.hiver_passe_max_m)+' m au plus creux':'')+(G.max_moyen_m!=null?' (moyenne '+n(G.max_moyen_m)+' m)':'')+(G.status==='stale'?' · données non mises à jour':'')+'</span>':'');
 $('chantier-note').textContent='Pluie : médiane des modèles pondérée par leur fiabilité mesurée pour la pluie @ probabilité la plus haute des sources. Heures sèches : heures de 7 h à 18 h sans pluie selon la médiane pondérée des modèles heure par heure (NBM et MétéoMédia, donnés par tranches de 6 h, n’y comptent pas). Foudre : menace d’éclairs prévue par le modèle HRRR (à confirmer par Environnement Canada). Sol : pluie des 14 derniers jours (Climat Québec ou pluviomètre le plus proche) qui sèche d’environ 15 % par jour, plus la pluie prévue. Pavage « Bon » : moins de 0,5 mm, moins de 40 %, 10 °C et plus, 8 h sèches et sol pas détrempé. Excavation « Bon » : moins de 3 mm, moins de 50 % et sol sec. Gel dans le sol : sonde du MTQ sous la chaussée déneigée de Saint-Georges (≈ 2 jours de décalage), prolongée avec les températures prévues; sous un terrain enneigé, le gel est moins creux. « Sol gelé » à 30 cm et plus. Forte pluie : début de 1,5 mm/h ou 4 mm en 3 h (médiane des modèles) ou orage annoncé par Environnement Canada. Érable (15 févr. au 30 avril) : « Bonne » coulée = nuit à -2 °C ou moins puis jour entre 3 et 10 °C; « Possible » = gel la nuit et dégel le jour hors de ces valeurs; « Nuit douce » = pas de gel, la coulée s’arrête. Les jours éloignés (en pâle) sont une tendance.';
 return {pave:anyPave?list(goodPave):null,exc:list(goodExc),sap:sugar?list(goodSap):null};
}
function sapDays(){
 // Coulée d'érable : nuit à -2 °C ou moins (la nuit d'avant, ou celle du jour) puis journée entre 3 et 10 °C.
 // Heure par heure (d.seve, modèles horaires) : une « bonne » journée sans au moins 4 h de dégel n'est que « possible ».
 const out=[];let prev=null;
 for(const d of (state.consensus||[])){const hi=d.high_mean,night=[prev,d.low_mean].filter(v=>v!=null),lo=night.length?Math.min(...night):null;prev=d.low_mean;
  let v=hi==null||lo==null?['—','']:lo<=-2&&hi>=3&&hi<=10?['Bonne','green']:lo<=0&&hi>0&&hi<=14?['Possible','amber']:hi<=0?['Gel (rien)','']:['Nuit douce','red'];
  const s=d.seve;if(s&&v[1]==='green'&&s.heures_degel<4)v=['Possible','amber'];
  out.push({d,lo,hi,v,s})}
 return out;
}
function mmdd(date){return (date.getMonth()+1)*100+date.getDate()}
function erabliere(){
 const E=state.erable;if(!E)return;
 const now=new Date(),md=mmdd(now),[a,b]=[E.onglet_visible.debut,E.onglet_visible.fin].map(x=>+x.replace('-','')),days=sapDays();
 // Un redoux de décembre ou de janvier n'est pas le début de la saison : on ne regarde les coulées prévues qu'à partir du 1er février.
 const first=days.findIndex((x,i)=>+x.d.date.slice(5).replace('-','')>=201&&+x.d.date.slice(5).replace('-','')<=430&&x.v[1]==='green'&&days.slice(i,i+7).filter(y=>y.v[1]==='green').length>=2);
 const visible=md>=a&&md<=b;
 $('tab-erabliere').hidden=!visible;if(!visible)return;
 const yr=now.getMonth()>=8?now.getFullYear()+1:now.getFullYear(),at=s=>new Date(yr+'-'+s+'T12:00:00-05:00');
 const pc=E.premiere_coulee||{},est=at(pc.estimation||pc.estimation_2027||pc.normale_1964_2024||'03-10'),lead=E.avance_entaillage_jours*86400e3,fmt=t=>new Intl.DateTimeFormat('fr-CA',{weekday:'long',day:'numeric',month:'long',timeZone:'America/Toronto'}).format(t);
 let start=est,how='estimation de saison (de '+fmt(at(E.premiere_coulee.plus_tot)).replace(/^\S+ /,'')+' au '+fmt(at(E.premiere_coulee.plus_tard)).replace(/^\S+ /,'')+')';
 if(first>=0){start=new Date(days[first].d.date+'T12:00:00-05:00');how='prévisions météo'}
 const tap=new Date(start-lead),left=Math.round((tap-now)/86400e3),startPast=start<now;
 const good=days.filter(x=>x.v[1]==='green').length,poss=days.filter(x=>x.v[1]==='amber').length;
 const title=startPast&&first>=0?'Ça coule : '+good+' bonne(s) journée(s) de coulée prévue(s).':left<=0?'Il est temps d’entailler.':'Entailler vers le '+fmt(tap)+'.';
 $('sap-status').className='signal '+(left<=0||first>=0?'watch':'calm');
 $('sap-status').innerHTML='<div><span class="tag '+(left<=0||first>=0?'amber':'green')+'">ENTAILLAGE · 1000 ENTAILLES</span><h2>'+esc(title)+'</h2><p>Première coulée attendue : <b>'+esc(fmt(start))+'</b> ('+esc(how)+'). On entaille environ '+E.avance_entaillage_jours+' jours avant'+(left>0?' : dans '+left+' jour'+(left>1?'s':'')+'.':'.')+'</p><ul class="sap-why">'+E.raisons.map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul></div>';
 $('sap-count').textContent=good+' bonnes · '+poss+' possibles';$('sap-count').className='tag '+(good?'green':'');
 $('sap-rows').innerHTML=days.map(x=>'<tr'+(x.d.tendance?' class="trend"':'')+'><td>'+esc(dayLabel(x.d.date).replace(/ \S+\.?$/,''))+'</td><td class="ico">'+symbol(x.d.risks)+'</td><td><span class="tag '+x.v[1]+'">'+x.v[0]+'</span></td><td>'+n(x.lo==null?null:Math.round(x.lo))+'°</td><td>'+n(x.hi==null?null:Math.round(x.hi))+'°</td><td>'+(x.s?x.s.heures_degel+' h'+(x.s.ecart_modeles_c!=null?' <small class="'+(x.s.ecart_modeles_c>4?'hot':'muted')+'" title="Écart moyen entre les modèles l’après-midi">'+(x.s.ecart_modeles_c>4?'incertain':'± '+n(x.s.ecart_modeles_c)+'°')+'</small>':''):'—')+'</td><td>'+(x.d.pop?x.d.pop.value+' %':'—')+'</td></tr>').join('');
 $('sap-note').textContent=E.regle+' Dégel : heures au-dessus de 0 °C entre 8 h et 20 h selon la médiane des modèles heure par heure; une « bonne » journée avec moins de 4 h de dégel devient « possible ». « Incertain » : les modèles diffèrent de plus de 4 °C l’après-midi. Les max et min viennent des sites, pondérés par leur fiabilité mesurée. Normale : environ '+E.jours_coulee_normale_mars_avril+' bonnes journées en mars et avril. Les jours éloignés (en pâle) sont une tendance.';
}
function homeTab(){const md=mmdd(new Date());return md>=1101||md<=415?'operations':'chantier'}
function observedSeason(records){
 // Mêmes règles que l'analyse historique : épisodes de 5 cm+ (pause d'un jour max) et sorties (5 cm accumulés).
 const rows=records.filter(r=>r.snow_cm!=null).slice().sort((a,b)=>a.date.localeCompare(b.date));
 const eps=[];let cur=null,last=null;
 for(const r of rows){if(r.snow_cm<0.2)continue;const t=Date.parse(r.date);if(cur&&t-last>2*86400000){eps.push(cur);cur=null}cur=cur||{start:r.date,total:0};cur.total+=r.snow_cm;last=t}
 if(cur)eps.push(cur);
 let acc=0,jours=0,fonte=0;const byMonth={};
 for(const r of rows){const s=r.snow_cm,rain=r.rain_mm||0;
  if(rain>=5&&acc+s>=2){fonte++;acc=0;continue} // la pluie fait fondre : abrasif et bord de rue, pas de déneigement
  if(s>=0.2){acc+=s}else if((r.tmax!=null&&r.tmax>=4)||rain>=2)acc=0; // les petites chutes s'additionnent jusqu'à un redoux
  if(acc>=5){jours++;acc=0}}
 // Vent : poudrerie (froid) ou glace (près de 0 °C) les jours sans tempête, avec 5 cm et plus au sol.
 let poudrerie=0,glaceVent=0;const vent=state.vent_saison||{},byDate=Object.fromEntries(rows.map(r=>[r.date,r]));
 for(const [day,g] of Object.entries(vent)){const r=byDate[day];if(!r||g<50||(r.depth_cm??0)<5||(r.snow_cm??0)>=5||r.tmax==null)continue;
  if(r.tmax<=0)poudrerie++;else if(r.tmax<=3)glaceVent++}
 for(const e of eps.filter(e=>e.total>=5)){const m=e.start.slice(5,7);byMonth[m]=(byMonth[m]||0)+1}
 let verglas=0,pluie=0;
 for(const r of records){const rain=r.rain_mm;if(rain==null||r.tmax==null||r.tmin==null)continue;
  if(rain>=1&&r.tmin<=-1&&r.tmax<=2)verglas++;else if(rain>=2&&['12','01','02','03'].includes(r.date.slice(5,7)))pluie++}
 return {poudrerie,glaceVent,t5:eps.filter(e=>e.total>=5).length,t15:eps.filter(e=>e.total>=15).length,t25:eps.filter(e=>e.total>=25).length,jours,fonte,verglas,pluie,byMonth};
}
function seasonBar(label,done,exp,norm,unit=''){
 if(!exp)return '';
 const max=Math.max(exp.max,norm,done,1),pct=v=>Math.min(100,v/max*100);
 return '<div class="season-row"><div class="season-label"><b>'+label+'</b><span>'+n(done)+unit+' à ce jour · '+n(exp.central)+unit+' attendus ('+n(exp.min)+'–'+n(exp.max)+')</span></div><div class="season-bar"><span class="range" style="left:'+pct(exp.min)+'%;width:'+(pct(exp.max)-pct(exp.min))+'%"></span><span class="done" style="width:'+pct(done)+'%"></span><i class="normal" style="left:'+pct(norm)+'%" title="Normale : '+n(norm)+unit+'"></i></div></div>';
}
function renderSeason(){
 const e=state.saison_estimation;if(!e){$('season-panel').hidden=true;return}$('season-panel').hidden=false;
 const o=observedSeason(state.climate.records),a=e.attendu_total,no=e.normale;
 // À pareille date : cet hiver, hiver dernier (mêmes règles) et normale des 15 hivers récents.
 const cut=state.climate.last_date;
 if(cut){const md=cut.slice(5),prevCut=(+cut.slice(0,4)-1)+cut.slice(4),P=state.precedent?.records?.filter(r=>r.date<=prevCut),N=state.normale_date?.par_date?.[md];
  const sum=rs=>rs.reduce((t,r)=>t+(r.snow_cm||0),0),cur=state.climate.records.filter(r=>r.date<=cut),p=P?.length?observedSeason(P):null;
  const lines=[['Neige tombée',sum(cur),P?.length?sum(P):null,N?.neige_cm,' cm'],['Tempêtes de 5 cm et plus',o.t5,p?.t5,N?.tempetes_5cm,''],['Grosses tempêtes (15 cm et plus)',o.t15,p?.t15,N?.tempetes_15cm,''],['Jours de déneigement',o.jours,p?.jours,N?.jours_deneigement,''],['Sorties d’abrasif après une fonte',o.fonte,p?.fonte,N?.sorties_fonte,''],['Jours de verglas probable',o.verglas,p?.verglas,N?.jours_verglas,''],['Jours de pluie en hiver (déc. à mars)',o.pluie,p?.pluie,N?.jours_pluie,'']];
  const f=(v,u)=>v==null?'—':n(Math.round(v*10)/10)+u,cls=(v,nv)=>v==null||nv==null?'':v>nv*1.15+0.4?'up':v<nv*0.85-0.4?'down':'';
  $('season-compare').innerHTML='<div class="section-heading"><h3>À pareille date · '+esc(new Intl.DateTimeFormat('fr-CA',{day:'numeric',month:'long',timeZone:'UTC'}).format(new Date(cut+'T12:00:00Z')))+'</h3></div><div class="table-scroll"><table class="cmp"><thead><tr><th></th><th>Cet hiver</th><th>Hiver dernier</th><th>Normale</th></tr></thead><tbody>'+lines.map(([l,a,b,c,u])=>'<tr><td>'+l+'</td><td class="'+cls(a,c)+'"><b>'+f(a,u)+'</b></td><td>'+f(b,u)+'</td><td class="muted">'+f(c,u)+'</td></tr>').join('')+'</tbody></table></div><p class="footnote">Cumuls du 1er octobre au '+esc(dateOnly(cut))+' (dernier relevé publié), mêmes règles pour les trois colonnes. Hiver dernier : '+esc(state.precedent?.season||'—')+(P?.length&&P[0].date>prevCut.slice(0,4)+'-10-15'?' (octobre manquant)':'')+'. Normale : moyenne des '+esc(state.normale_date?.periode||'15 hivers récents')+'. En vert : sous la normale; en orange : au-dessus.</p>';
 }
 $('season-updated').textContent='Estimation du '+dateOnly(e.mis_a_jour);
 $('season-progress').innerHTML='<p class="muted">Ce qui est tombé depuis le 1er octobre (relevés publiés) comparé à ce qu’on attend pour tout l’hiver '+esc(e.saison)+'. Le trait blanc marque la normale.</p>'+seasonBar('Tempêtes de 5 cm et plus',o.t5,a.tempetes_5cm,no.tempetes_5cm)+seasonBar('Grosses tempêtes (15 cm et plus)',o.t15,a.tempetes_15cm,no.tempetes_15cm)+seasonBar('Sorties de déneigement au total (neige + poudrerie)',o.jours+o.poudrerie,a.sorties_total,no.sorties_total)+seasonBar('Jours de déneigement (neige)',o.jours,a.jours_deneigement,no.jours_deneigement)+seasonBar('Sorties de poudrerie (vent, sans tempête)',o.poudrerie,a.sorties_poudrerie,no.sorties_poudrerie)+seasonBar('Sorties d’abrasif après une fonte',o.fonte,a.sorties_fonte,no.sorties_fonte)+seasonBar('Glace au sol par grand vent (abrasif)',o.glaceVent,a.jours_glace_vent,no.jours_glace_vent)+seasonBar('Jours de verglas probable (pluie qui gèle)',o.verglas,a.jours_verglas,no.jours_verglas)+seasonBar('Jours de pluie en hiver (déc. à mars)',o.pluie,a.jours_pluie,no.jours_pluie)+seasonBar('Neige totale',state.climate.total_cm||0,a.neige_cm,no.neige_cm,' cm');
 const nx=state.consensus||[],cnt=k=>nx.filter(d=>(d.risks||[]).includes(k)).length;
 $('season-progress').innerHTML+='<div class="season-next"><b>Dans les 14 prochains jours</b><span>❄ '+cnt('Neige')+' jour(s) de neige</span><span>🌧 '+(cnt('Pluie')+cnt('Pluie / neige'))+' jour(s) de pluie ou pluie et neige</span><span class="'+(cnt('Verglas / grésil')?'ice':'')+'">⚠ '+cnt('Verglas / grésil')+' jour(s) de verglas ou grésil</span><span class="'+(cnt('Poudrerie')+cnt('Glace (vent)')?'ice':'')+'">💨 '+cnt('Poudrerie')+' jour(s) de poudrerie · '+cnt('Glace (vent)')+' de glace par grand vent</span></div>';
 const names={'11':'nov.','12':'déc.','01':'janv.','02':'févr.','03':'mars','04':'avr.'};
 $('season-months').innerHTML=Object.entries(e.par_mois).map(([m,v])=>'<div><small>'+names[m]+'</small><strong>'+n(o.byMonth[m]||0)+'<span> / '+n(v)+'</span></strong></div>').join('');
 $('season-why').innerHTML='<ul>'+e.raisons.map(r=>'<li>'+esc(r)+'</li>').join('')+'</ul><p class="footnote">'+esc(e.regle_sorties)+' '+esc(e.regle_verglas||'')+' '+esc(e.regle_vent||'')+' Normale : '+esc(no.periode)+'. Prochaine révision : '+esc(e.prochaine_revision)+'.</p><p class="footnote">Sources : '+e.sources.map(s=>'<a href="'+esc(s.url)+'" target="_blank" rel="noopener">'+esc(s.nom)+' ↗</a>').join(' · ')+'</p>';
}
function renderWinter(){renderSeason();
 const rows=state.climate.records,months={};
 for(const r of rows){const m=r.date.slice(0,7);if(!months[m])months[m]={total:0,count:0};if(r.snow_cm!=null){months[m].total+=r.snow_cm;months[m].count++}}
 const max=Math.max(1,...Object.values(months).map(m=>m.total));
 $('monthly').innerHTML=Object.entries(months).map(([m,v])=>'<div class="month-row"><span>'+esc(new Intl.DateTimeFormat('fr-CA',{month:'long',timeZone:'America/Toronto'}).format(new Date(m+'-15T12:00:00Z')))+'</span><div class="bar"><span style="width:'+Math.max(v.total?2:0,v.total/max*100)+'%"></span></div><strong>'+n(v.total)+' cm</strong></div>').join('')||'<p class="empty">Les relevés seront ajoutés dès leur publication.</p>';
 const chosen=$('month-filter').value;$('month-filter').innerHTML='<option value="all">Tous les mois</option>'+Object.keys(months).map(m=>'<option value="'+m+'">'+m+'</option>').join('');if([...$('month-filter').options].some(o=>o.value===chosen))$('month-filter').value=chosen;
 renderWinterRows();
}
function renderWinterRows(){if(!state)return;const month=$('month-filter').value;const rows=state.climate.records.filter(r=>month==='all'||r.date.startsWith(month)).slice().reverse();$('winter-rows').innerHTML=rows.map(r=>'<tr><td>'+esc(r.date)+'</td><td>'+n(r.snow_cm)+(r.snow_cm!=null?' cm':'')+'</td><td>'+n(r.rain_mm)+(r.rain_mm!=null?' mm':'')+'</td><td>'+n(r.depth_cm)+(r.depth_cm!=null?' cm':'')+'</td><td>'+esc(r.snow_cm==null?'Non disponible':r.snow_flag||'Valeur publiée')+'</td></tr>').join('')||'<tr><td colspan="5">Aucun relevé disponible.</td></tr>'}
function csv(){if(!state)return;const lines=['Date;Neige_cm;Pluie_mm;Neige_au_sol_cm;Indicateur;Source',...state.climate.records.map(r=>[r.date,r.snow_cm??'',r.rain_mm??'',r.depth_cm??'',r.snow_flag,r.source].map(x=>'"'+String(x).replaceAll('"','""')+'"').join(';'))];const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Saint-Prosper-hiver-'+state.climate.season+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function tab(name){document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!==name);document.querySelectorAll('[data-tab]').forEach(e=>{e.classList.toggle('active',e.dataset.tab===name);e.setAttribute('aria-current',e.dataset.tab===name?'page':'false')});if(name==='radar'){initRadar();setTimeout(()=>map?.invalidateSize(),100)}if(name==='operations'&&state){initMini()}if(name==='motoneige'&&state){initMotoMap()}}
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
if('serviceWorker'in navigator){navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).then(r=>r.update()).catch(()=>{});
 // Nouvelle version publiée : recharger une fois pour l'afficher tout de suite.
 let reloaded=false;navigator.serviceWorker.addEventListener('controllerchange',()=>{if(!reloaded){reloaded=true;location.reload()}})}
const VAPID_PUBLIC='BPaBeYPCMQ81QiCRF-FnyjtmV1Xm9PaMKuPGvMblz5ACoCVPS6SLSTq_NAbUTUSn7HNWwpMyuLq4xsxqnGE0Eb4',REG_URL='https://ntfy.sh/dulac-deneigement-inscriptions-k7p2';
function b64u(s){const p='='.repeat((4-s.length%4)%4),b=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from(b,c=>c.charCodeAt(0))}
const isIOS=/iPhone|iPad|iPod/.test(navigator.userAgent),standalone=window.navigator.standalone===true||matchMedia('(display-mode: standalone)').matches;
async function pushState(){
 if(isIOS&&!standalone)return 'ios-browser';
 if(!('serviceWorker'in navigator)||!('PushManager'in window)||!('Notification'in window))return 'unsupported';
 const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();
 return sub?'on':Notification.permission==='denied'?'denied':'off';
}
async function renderPush(){
 let s;try{s=await pushState()}catch{s='unsupported'}
 const help={'ios-browser':'Sur iPhone, ajoute d’abord le site à l’écran d’accueil (Partager → « Sur l’écran d’accueil »), puis ouvre-le depuis l’icône.','unsupported':'Ce navigateur ne permet pas les notifications.','denied':'Les notifications sont bloquées pour ce site : les réactiver dans les réglages du téléphone.','off':'Pas encore activées sur ce téléphone.','on':'Activées sur ce téléphone.'}[s];
 $('push-help').textContent=help;$('push-tag').textContent=s==='on'?'Activées':'Désactivées';$('push-tag').className='tag '+(s==='on'?'green':'');
 $('push-on').hidden=s==='on';$('push-on').disabled=s!=='off';$('push-off').hidden=s!=='on';$('push-label').hidden=s==='on';
 let dismissed=false;try{dismissed=localStorage.getItem('push-banner-off')==='1'}catch{}
 $('push-banner').hidden=!(s==='off'||s==='ios-browser')||dismissed;
}
async function enablePush(){
 try{
  if(await pushState()==='ios-browser'){tab('sources');$('push-panel').scrollIntoView({behavior:'smooth'});return}
  const perm=await Notification.requestPermission();if(perm!=='granted'){await renderPush();return}
  const reg=await navigator.serviceWorker.ready;
  const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64u(VAPID_PUBLIC)});
  const r=await fetch(REG_URL,{method:'POST',body:JSON.stringify({action:'add',subscription:sub.toJSON(),label:$('push-label').value.trim()})});
  if(!r.ok)throw Error('Inscription non transmise');
  reg.showNotification('Notifications activées sur ce téléphone',{body:'Le robot confirmera à sa prochaine mise à jour.',icon:'icon.svg'});
 }catch(e){$('push-help').textContent='Activation impossible : '+e.message}
 renderPush();
}
async function disablePush(){
 try{const reg=await navigator.serviceWorker.ready,sub=await reg.pushManager.getSubscription();if(sub){await fetch(REG_URL,{method:'POST',body:JSON.stringify({action:'remove',subscription:sub.toJSON()})}).catch(()=>{});await sub.unsubscribe()}}catch{}
 renderPush();
}
$('push-on').addEventListener('click',enablePush);$('push-banner-on').addEventListener('click',enablePush);$('push-off').addEventListener('click',disablePush);
renderPush();
function spark(series){
 const pts=series.filter(s=>s.depth_cm!=null);if(pts.length<2)return '';
 const t0=Date.parse(series[0].time),t1=Date.parse(series.at(-1).time)||t0+1,max=Math.max(5,...pts.map(p=>p.depth_cm));
 const x=t=>((Date.parse(t)-t0)/(t1-t0||1)*200).toFixed(1),y=v=>(38-v/max*34).toFixed(1);
 return '<svg class="spark" viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true"><path d="M'+pts.map(p=>x(p.time)+' '+y(p.depth_cm)).join('L')+'" fill="none" stroke="#FFB81C" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>';
}
function trend(c){if(c==null)return '<span class="muted">—</span>';if(c<=-2)return '<span class="melt">▼ '+n(Math.abs(c))+' cm</span>';if(c>=2)return '<span class="gain">▲ '+n(c)+' cm</span>';return '<span class="muted">stable</span>'}
function renderDepth(){
 const d=state.snow_depth,recs=(state.climate.records||[]).filter(r=>r.depth_cm!=null);
 const sp=recs.at(-1),prev=recs.at(-2);
 let rows='<div class="depth-row home"><div><b>Saint-Prosper</b><small>Climat Québec · 1 relevé par jour'+(sp?' · '+dateOnly(sp.date):'')+'</small></div><strong>'+(sp?n(sp.depth_cm)+' cm':'—')+'</strong><div>'+trend(sp&&prev?sp.depth_cm-prev.depth_cm:null)+'<small>sur 1 jour</small></div><div></div></div>';
 const st=(d?.stations||[]);
 rows+=st.map(s=>'<div class="depth-row"><div><b>'+esc(s.name)+'</b><small>'+s.km+' km · capteur horaire'+(s.latest?' · '+local(s.latest.time,{month:undefined,day:undefined}):'')+(s.temp!=null?' · '+n(s.temp)+' °C':'')+'</small></div><strong>'+(s.status!=='ok'?'<span class="muted">indisponible</span>':s.latest?n(s.latest.depth_cm)+' cm':'—')+'</strong><div>'+trend(s.change_24h)+'<small>sur 24 h</small></div><div>'+spark(s.series||[])+'</div></div>').join('');
 $('depth').innerHTML=rows;
 const ch=st.filter(s=>s.change_24h!=null),warm=st.some(s=>s.temp!=null&&s.temp>0);
 const melt=ch.some(s=>s.change_24h<=-2),gain=ch.some(s=>s.change_24h>=2),any=st.some(s=>s.latest?.depth_cm>0)||(sp?.depth_cm>0);
 const label=!any?'Pas de neige au sol':gain?'Accumulation en cours':melt?(warm?'Fonte en cours':'Tassement'):'Couvert stable';
 $('depth-state').textContent=label;$('depth-state').className='tag '+(melt&&warm?'amber':gain?'green':'');
 $('depth-note').textContent=(d?.note||'')+' La courbe montre les 72 dernières heures.';
}
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
 $('reliability').innerHTML='<h3>Hiver dernier, prévision de la veille'+per(hist[0])+'</h3>'+relTable(hist)+'<p class="footnote">Seuls les modèles dont les prévisions passées sont archivées publiquement (européens et américain) peuvent être évalués sur l’hiver dernier.</p><h3>Cet hiver, toutes les sources suivies'+per(live[0])+'</h3>'+relTable(live)+'<p class="footnote">Se remplit chaque jour à partir des archives du robot : MétéoMédia, Weather Underground (jusqu’au 23 novembre), modèles canadiens, européen, américain, MET Norway et le consensus du plan.</p>';
 if(hist[0])$('reliability-tag').textContent='Meilleur hiver dernier : '+hist[0].nom;
 const c=state.confiance,names={};(state.models||[]).forEach(m=>names[m.id]=m.name);
 if(c&&Object.keys(c).length){
  const rows=Object.entries(c).sort((a,b)=>b[1].poids-a[1].poids);
  $('reliability').insertAdjacentHTML('afterbegin','<h3>Poids accordé à chaque source en ce moment</h3><div class="table-scroll"><table class="rel"><thead><tr><th>Source</th><th>Poids</th><th>Erreur retenue</th><th>Épisodes mesurés</th><th>État</th></tr></thead><tbody>'+rows.map(([k,v])=>'<tr><td>'+esc(names[k]||k)+'</td><td><span class="pbar"><i style="width:'+Math.round(v.poids*100)+'%"></i></span><b>'+n(v.poids)+'</b></td><td>'+n(v.erreur_cm)+' cm</td><td>'+v.episodes+(v.episodes?' <span class="muted">('+v.historique+' hiver dernier · '+v.cet_hiver+' cet hiver)</span>':'')+'</td><td><span class="tag '+(v.statut==='mesurée'?'green':v.statut==='en rodage'?'amber':'')+'">'+esc(v.statut)+'</span></td></tr>').join('')+'</tbody></table></div><p class="footnote">Recalculé automatiquement à chaque passage du robot : chaque épisode de neige mesuré par Climat Québec est comparé à ce que chaque source prévoyait la veille. Plus l’erreur est petite, plus la source pèse dans le plan de sortie (médiane pondérée). Une source peu mesurée part d’une erreur par défaut de 7 cm et s’en détache à mesure que les épisodes s’accumulent; ceux de cet hiver comptent 1,5 fois plus. Un risque annoncé par les sites (verglas, pluie sur la neige…) n’envoie une alerte que s’il vient d’Environnement Canada, de 2 sources, ou d’une source mesurée de poids 0,6 et plus; sinon il est affiché « à confirmer ».</p>');
 }
}
const hhmm=v=>v?new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',hour:'numeric',minute:'2-digit'}).format(new Date(v)):'—';
const dayOf=v=>new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'long',day:'numeric',month:'long'}).format(new Date(v));
function between(a,b){if(!a||hhmm(a)===hhmm(b))return '';if(!b)return ' (dès '+hhmm(a)+' selon le modèle le plus enneigé; jamais selon le moins enneigé)';return ' (entre '+hhmm(a)+' et '+hhmm(b)+' selon les modèles)'}
function renderPlan(){
 const models=state.models||[],ok=models.filter(m=>m.status==='ok');
 $('plan-models').textContent=ok.length+' / '+models.length+' modèles';$('plan-models').className='tag '+(ok.length>=2?'green':'amber');
 const wt=m=>m.confiance?' · poids '+n(m.confiance.poids):'',wtip=m=>m.confiance?'Confiance : poids '+n(m.confiance.poids)+', erreur retenue '+n(m.confiance.erreur_cm)+' cm par épisode, '+m.confiance.episodes+' épisodes mesurés ('+m.confiance.statut+'). ':'';
 $('model-list').innerHTML=models.slice().sort((a,b)=>(b.confiance?.poids||0)-(a.confiance?.poids||0)).map(m=>'<span class="tag '+(m.status!=='ok'?'amber':(m.confiance?.poids||0)>=0.6?'green':'')+'" title="'+esc(wtip(m)+(m.error||m.note||''))+'">'+esc(m.name)+(m.status==='ok'?wt(m):' · indisponible')+'</span>').join(' ');
 const plans=state.plan||[];
 if(!models.length)$('plan').innerHTML='<p class="muted">Le plan de sortie apparaîtra après la prochaine collecte du robot.</p>';
 else if(!plans.length)$('plan').innerHTML='<div class="plan-card calm"><strong>Aucune sortie prévue</strong><p class="muted">Les modèles ne prévoient pas d’épisode de neige approchant '+(state.plan_config?.seuil_cm||5)+' cm dans les 72 prochaines heures.</p></div>';
 else $('plan').innerHTML=plans.map(p=>{
  const go=p.statut!=='sous_seuil',tag=p.statut==='sortie'?'SORTIE PRÉVUE':p.statut==='possible'?'SORTIE POSSIBLE':'SOUS LE SEUIL';
  let html='<div class="plan-card '+(p.statut==='sortie'?'go':p.statut==='possible'?'maybe':'calm')+'"><div class="plan-top"><span class="tag '+(p.statut==='sortie'?'amber':'')+'">'+tag+'</span><span class="muted">Confiance '+esc(p.confiance.toLowerCase())+' · '+p.modeles+' modèle'+(p.modeles>1?'s':'')+'</span></div>';
  if(go){html+='<h3>'+esc(dayOf(p.depart))+'</h3><div class="plan-times"><div><label>Départ</label><strong>'+hhmm(p.depart)+'</strong></div>'+(p.echeance?'<div><label>Propre pour</label><strong>'+hhmm(p.echeance)+'</strong></div>':'<div><label>Fin de tournée</label><strong>≈ '+hhmm(p.fin_tournee)+'</strong></div>')+'<div><label>Fin de la tempête</label><strong>≈ '+hhmm(p.fin)+'</strong></div>'+(p.final?'<div><label>'+finalLbl(p.final)+'</label><strong>'+hhmm(p.final.heure)+'</strong></div>':'')+'</div>';
   html+='<ul class="plan-facts"><li>'+n(p.plan_config_seuil||state.plan_config?.seuil_cm||5)+' cm atteints vers <b>'+hhmm(p.seuil_atteint||p.seuil_fourchette[0])+'</b>'+esc(between(p.seuil_fourchette[0],p.seuil_fourchette[1]))+'</li><li>Neige de l’épisode : <b>≈ '+n(p.total_cm)+' cm</b> (fourchette '+n(p.fourchette_cm[0])+'–'+n(p.fourchette_cm[1])+' cm), du '+esc(dayOf(p.debut))+' '+hhmm(p.debut)+' au '+(dayOf(p.fin)===dayOf(p.debut)?'':esc(dayOf(p.fin))+' ')+hhmm(p.fin)+'</li>'+(p.ensemble?'<li>Ensemble européen (51 versions du modèle) : <b>'+p.ensemble.prob_5cm+' %</b> de chances de 5 cm ou plus ce jour-là · médiane '+n(p.ensemble.p50_cm)+' cm, de '+n(p.ensemble.p10_cm)+' à '+n(p.ensemble.p90_cm)+' cm (10–90 %)</li>':'')+(p.fiables?.length?'<li>Selon les modèles, du plus fiable au moins fiable : '+p.fiables.map(r=>esc(r.nom.split(' (')[0].split(' ·')[0])+' <b>'+n(r.cm)+' cm</b>'+(r.statut==='mesurée'?'':' <span class="muted">('+esc(r.statut)+')</span>')).join(' · ')+'</li>':'')+'<li>Tournée de <b>'+n(p.duree_h)+' h</b> par machine'+(p.neige_a_echeance_cm!=null?' pour ≈ '+n(p.neige_a_echeance_cm)+' cm tombés à l’échéance':'')+'</li>'+(p.final?'<li>'+(p.final.type==='reprise_matin'?'Passage rapide en fin de journée, puis reprise le lendemain matin (propre pour '+hhmm(p.final.echeance)+')':p.final.type==='deuxieme_tournee'?'2e tournée complète':'Nettoyage final')+' : ≈ '+n(p.final.neige_cm)+' cm tombés après '+(p.final.type==='reprise_matin'?'le passage du soir':'le départ')+(p.final.duree_h?' · '+n(p.final.duree_h)+' h':'')+'</li>':'<li>Pas de nettoyage final prévu : la neige cesse avant ou peu après le départ.</li>')+'</ul>';}
  else html+='<p>'+esc(p.resume)+'</p>';
  if(p.notes?.length)html+='<ul class="plan-notes">'+p.notes.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>';
  return html+'</div>'}).join('');
 const hours=(state.hourly_snow||[]).filter(h=>Date.parse(h.time)+3600000>Date.now()).slice(0,48);
 if(!hours.length){$('timeline').innerHTML='<p class="muted">Aucune série horaire disponible.</p>';return}
 const max=Math.max(1,...hours.map(h=>h.hi)),marks={};
 for(const p of plans){if(p.depart)marks[new Date(p.depart).setMinutes(0,0,0)]='Départ';if(p.final)marks[new Date(p.final.heure).setMinutes(0,0,0)]=finalLbl(p.final)}
 $('timeline').innerHTML=hours.map((h,i)=>{const t=Date.parse(h.time),hr=+new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',hour:'numeric',hourCycle:'h23'}).formatToParts(new Date(t)).find(x=>x.type==='hour').value,mark=marks[t];
  return '<div class="tl-col'+(hr===0?' midnight':'')+(mark?' mark':'')+'" title="'+esc(hhmm(h.time)+' · '+n(h.snow_cm)+' cm/h (de '+n(h.lo)+' à '+n(h.hi)+') · '+h.n+' modèles')+'"><div class="tl-bar"><span class="tl-range" style="bottom:'+(h.lo/max*100)+'%;height:'+Math.max(0,(h.hi-h.lo)/max*100)+'%"></span><span class="tl-med" style="height:'+(h.snow_cm/max*100)+'%"></span></div>'+(mark?'<em>'+esc(mark)+'</em>':'')+'<small>'+(hr===0?esc(new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'short'}).format(new Date(t))):hr%3===0?hr+'h':'')+'</small></div>'}).join('');
}
function renderNbm(){
 const p=state.nbm_proba,tr=(p?.tranches||[]).filter(t=>Date.parse(t.fin)>Date.now());
 $('nbm-panel').hidden=!tr.length;if(!tr.length)return;
 const best=Math.max(0,...tr.map(t=>t.p_5cm??0));
 $('nbm-tag').textContent=best>=50?'5 cm+ probable':best>=20?'5 cm+ possible':'NOAA NBM';$('nbm-tag').className='tag '+(best>=50?'amber':best>=20?'':'green');
 if(!tr.some(t=>(t.p_2_5cm||0)>0||(t.snow_cm||0)>=0.5)){$('nbm').innerHTML='<p class="muted">Aucune chance de neige d’ici '+esc(dayOf(tr.at(-1).fin))+' selon la synthèse américaine : 0 % de 2,5 cm et plus sur chaque tranche de 6 h.</p>';return}
 const bar=v=>v==null?'<span class="muted">—</span>':'<span class="pbar"><i style="width:'+Math.max(0,Math.min(100,v))+'%"></i></span><b class="'+(v>=50?'hi':'')+'">'+v+' %</b>';
 $('nbm').innerHTML='<div class="table-scroll"><table class="nbm"><thead><tr><th>Tranche</th><th>Neige</th><th>2,5 cm et +</th><th>5 cm et +</th><th>Temp.</th></tr></thead><tbody>'+tr.map(t=>'<tr><td>'+esc(new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'short',day:'numeric'}).format(new Date(t.debut)))+' · '+hhmm(t.debut)+'–'+hhmm(t.fin)+'</td><td>'+(t.snow_cm==null?'—':n(t.snow_cm)+' cm')+'</td><td>'+bar(t.p_2_5cm)+'</td><td>'+bar(t.p_5cm)+'</td><td>'+n(t.temp)+'°</td></tr>').join('')+'</tbody></table></div>';
}
const GRAV=[['Dégagée','green'],['À surveiller',''],['Enneigée','amber'],['Glacée','red']];
function renderRoutes(){
 const r=state.routes,segs=r?.segments||[];
 $('routes-panel').hidden=!r||r.status==='unavailable'&&!segs.length;if($('routes-panel').hidden)return;
 const g=r.resume?.gravite??0;$('routes-tag').textContent=r.resume?GRAV[g][0]+' · '+(segs[0]?.route||''):'—';$('routes-tag').className='tag '+GRAV[g][1];
 const since=v=>v?local(String(v).replace(/\//g,'-').replace(' ','T')+(/[Z+]/.test(v)?'':'-05:00')):'—';
 $('routes-rows').innerHTML=segs.slice(0,8).map(s=>'<tr><td><b>'+esc(s.route)+'</b><small>'+n(s.km)+' km</small></td><td>'+esc(s.de||'')+' → '+esc(s.a||'')+'</td><td><span class="tag '+GRAV[s.gravite||0][1]+'">'+esc(s.chaussee||'—')+'</span>'+(s.lames_neige?' <span class="tag amber">Lames de neige</span>':'')+'</td><td>'+esc(s.visibilite||'—')+'</td><td>'+esc(since(s.depuis))+'</td></tr>').join('')||'<tr><td colspan="5" class="muted">Aucun tronçon publié dans le secteur.</td></tr>';
 const ev=r.evenements||[];
 $('routes-events').innerHTML=ev.length?'<ul class="route-events">'+ev.slice(0,6).map(e=>'<li><span class="tag amber">'+esc(e.entrave||'Avertissement')+'</span> '+esc([e.route&&('Route '+e.route),e.lieu,e.municipalite,e.direction&&('direction '+e.direction.toLowerCase())].filter(Boolean).join(' · '))+(e.cause?' <span class="muted">('+esc(e.cause)+')</span>':'')+'</li>').join('')+'</ul>':'';
 const cams=r.cameras||[];
 $('cameras').innerHTML=cams.map(c=>'<figure class="cam" data-video="'+esc(c.video)+'"><button class="cam-play" aria-label="Voir la caméra '+esc(c.nom)+'">▶ Voir</button><figcaption>'+esc(c.nom)+'<small>'+n(c.km)+' km'+(c.page?' · <a href="'+esc(c.page)+'" target="_blank" rel="noopener">Québec 511 ↗</a>':'')+'</small></figcaption></figure>').join('')||'<p class="muted">Aucune caméra dans le secteur.</p>';
 document.querySelectorAll('.cam-play').forEach(b=>b.onclick=()=>{const f=b.closest('.cam');b.outerHTML='<video src="'+esc(f.dataset.video)+'" autoplay muted loop playsinline controls></video>'});
 $('routes-note').textContent='État des routes noté par les patrouilleurs du ministère des Transports (Québec 511, données ouvertes), lu à '+hhmm(r.fetched_at)+'. « Lames de neige » : bandes de neige soufflée sur la chaussée. Les vidéos sont chargées en direct depuis Québec 511.';
}
const SURF_C={'Poudreuse':'green','Neige fraîche':'green','Bonne base':'green','Ventée / tapée':'amber','Base mince':'amber','Lourde (redoux)':'amber','Croûte / glacée':'red','Pas de neige':''};
const motoSeason=()=>{const md=mmdd(new Date());return md>=1115||md<=430}; // motoneige : 15 novembre au 30 avril seulement
let motoMap=null,motoMarkers=null;
function initMotoMap(){
 const M=state?.motoneige;if(!M||typeof L==='undefined')return;
 const spots=M.endroits||[],noteOf=s=>Math.max(0,...(s.fin_de_semaine||[]).map(d=>d.note));
 if(!motoMap){
  motoMap=L.map('moto-map',{scrollWheelZoom:false}).setView([46.6,-70.6],7);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:14,attribution:'Fond © Esri'}).addTo(motoMap);
  // Terres publiques (PATP) : le service WMS ne dessine pas les zones; on passe par l'export ArcGIS, tuile par tuile.
  const Export=L.TileLayer.extend({getTileUrl(c){const s=this.getTileSize(),nw=L.CRS.EPSG3857.project(this._map.unproject([c.x*s.x,c.y*s.y],c.z)),se=L.CRS.EPSG3857.project(this._map.unproject([(c.x+1)*s.x,(c.y+1)*s.y],c.z));
   return 'https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/PATP_prov_WMS/MapServer/export?'+new URLSearchParams({bbox:[nw.x,se.y,se.x,nw.y].join(','),bboxSR:3857,imageSR:3857,size:s.x+','+s.y,layers:'show:1',format:'png32',transparent:'true',f:'image'})}});
  new Export('',{opacity:.42,attribution:'Terres publiques © MRNF Québec'}).addTo(motoMap);
  L.tileLayer.wms('https://geo.environnement.gouv.qc.ca/donnees/services/Biodiversite/Aires_protegees/MapServer/WMSServer',{layers:'AP_-_Parcs_nationaux_du_Québec_-_MELCCFP_Parcs5969',format:'image/png',transparent:true,version:'1.3.0',opacity:.6,attribution:'Parcs nationaux © MELCCFP'}).addTo(motoMap);
  fetch('terres-maine.geojson').then(r=>r.ok?r.json():null).then(g=>{if(g)L.geoJSON(g,{style:{color:'#5FCB8E',weight:1,fillColor:'#5FCB8E',fillOpacity:.35},onEachFeature:(f,l)=>l.bindPopup('<b>'+esc(f.properties.nom)+'</b><br>Terre publique de l’État du Maine · '+f.properties.ha+' ha')}).addTo(motoMap)}).catch(()=>{});
  L.circleMarker([46.214,-70.486],{radius:6,color:'#fff',weight:2,fillColor:'#FFB81C',fillOpacity:1}).addTo(motoMap).bindPopup('Saint-Prosper (départ)');
 }
 if(motoMarkers)motoMap.removeLayer(motoMarkers);
 const col=n=>n>=6?'#5FCB8E':n>=4?'#FFB81C':'#8394B0',drive=m=>Math.floor(m/60)+' h '+String(m%60).padStart(2,'0');
 motoMarkers=L.layerGroup(spots.map(s=>L.circleMarker([s.lat,s.lon],{radius:9,color:'#0B1322',weight:2,fillColor:col(noteOf(s)),fillOpacity:1}).bindPopup('<b>'+esc(s.nom)+'</b><br>'+esc(s.terre||'')+'<br>Route : '+drive(s.route_min)+' · '+s.km+' km<br>Fin de semaine : '+noteOf(s)+'/10'+(s.note?'<br><small>'+esc(s.note)+'</small>':'')+(s.lien?'<br><a href="'+esc(s.lien)+'" target="_blank" rel="noopener">Carte ITS : accès, stationnements ↗</a>':'')))).addTo(motoMap);
 motoMap.fitBounds(L.latLngBounds(spots.map(s=>[s.lat,s.lon]).concat([[46.214,-70.486]])),{padding:[24,24]});
 setTimeout(()=>motoMap.invalidateSize(),60);
}
function renderMoto(){
 const M=state.motoneige,on=!!M&&motoSeason();$('tab-motoneige').hidden=!on;if(!on){if(!$('motoneige').hidden)tab('operations');return}
 const spots=M.endroits||[],byId=Object.fromEntries(spots.map(s=>[s.id,s])),drive=m=>Math.floor(m/60)+' h '+String(m%60).padStart(2,'0');
 const we=spots[0]?.fin_de_semaine||[];if(we[0])$('moto-sat').textContent=dayLabel(we[0].date).replace(/ \S+\.?$/,'');if(we[1])$('moto-sun').textContent=dayLabel(we[1].date).replace(/ \S+\.?$/,'');
 const cell=d=>d?'<b class="moto-note n'+Math.min(10,Math.round(d.note))+'">'+d.note+'/10</b> <span class="tag '+(SURF_C[d.surface]??'')+'">'+esc(d.surface)+'</span><small>base ≈ '+d.base_cm+' cm'+(d.fraiche_48h_cm>=1?' · +'+n(d.fraiche_48h_cm)+' cm en 48 h':'')+(d.pluie_mm>=0.5?' · pluie '+n(d.pluie_mm)+' mm':'')+'</small>':'—';
 const ranked=(M.classement||[]).map(k=>byId[k]).filter(Boolean),best=ranked[0],top=s=>s?Math.max(0,...s.fin_de_semaine.map(d=>d.note)):0,bestNote=top(best);
 const ok=bestNote>=4;
 $('moto-status').className='signal '+(ok?'watch':'calm');
 $('moto-status').innerHTML='<div><span class="tag '+(ok?'green':'')+'">FIN DE SEMAINE</span><h2>'+(ok?esc(best.nom)+' : '+bestNote+'/10, '+drive(best.route_min)+' de route':'Pas encore de conditions de hors-piste.')+'</h2><p>'+(ok?'Meilleur rapport conditions / route. '+(top(ranked[1])>=4?'Ensuite : '+esc(ranked[1].nom)+'.':''):'Aucun endroit n’a assez de base prévue (15 cm et plus) pour la fin de semaine.')+'</p></div>';
 $('moto-tag').textContent=M.status==='stale'?'Données anciennes':'NBM · HRDPS · HRRR';$('moto-tag').className='tag '+(M.status==='stale'?'amber':'');
 const order=ranked.length?ranked:spots;
 $('moto-rows').innerHTML=order.map(s=>{const sat=s.fin_de_semaine[0],sun=s.fin_de_semaine[1],sol=s.neige_sol?.cm,v=s.variation_72h_cm;
  return '<tr><td><b>'+esc(s.nom)+'</b>'+(s.terre?'<small>'+esc(s.terre)+'</small>':'')+(s.note?'<small>'+esc(s.note)+'</small>':'')+(s.lien?'<small><a href="'+esc(s.lien)+'" target="_blank" rel="noopener">Carte ITS : accès, stationnements ↗</a></small>':'')+'</td><td>'+drive(s.route_min)+'<small>'+s.km+' km</small></td><td>'+(sol==null?'—':n(sol)+' cm')+(v!=null?'<small class="'+(v>=2?'gain':v<=-2?'melt':'')+'">'+(v>0?'+':'')+n(v)+' cm en 72 h</small>':'')+'</td><td>'+cell(sat)+'</td><td>'+cell(sun)+'</td><td><b>'+(s.vaut_la_route==null?'—':n(s.vaut_la_route))+'</b></td></tr>'}).join('');
 $('moto-details').innerHTML=order.map(s=>'<details class="moto-days"><summary>'+esc(s.nom)+' · 7 jours</summary><div class="table-scroll"><table class="moto"><tbody>'+s.jours.map(d=>'<tr><td>'+esc(dayLabel(d.date).replace(/ \S+\.?$/,''))+'</td><td>'+cell(d)+'</td><td>'+n(d.tmax)+'°'+(d.rafales_kmh>=40?'<small>💨 '+d.rafales_kmh+' km/h</small>':'')+'</td></tr>').join('')+'</tbody></table></div></details>').join('');
 $('moto-note').textContent='Note de 0 à 10 : base de neige (0 à 5 points : 15, 25, 35, 50, 70 cm) + surface (poudreuse +4, neige fraîche +2, bonne base +1, ventée 0, lourde −1, croûte −2) − pluie. Moins de 15 cm de base : 2/10 au plus (roches et souches). « Vaut la route » : la meilleure note de la fin de semaine moins 1 point par heure de route au-delà de la première. Croûte : dégel ou pluie dans les 72 h puis regel, sans 5 cm de neige fraîche par-dessus. '+(M.note||'')+' Temps de route : vitesses d’été, depuis Saint-Prosper.';
}
function renderTransport(){
 const r=state.routes||{},g=r.degel,tw=r.travaux||[];
 $('transport-panel').hidden=!g&&!tw.length;if($('transport-panel').hidden)return;
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Toronto'}).format(new Date());
 if(g?.debut&&g?.fin){
  const on=today>=g.debut&&today<=g.fin,soon=today<g.debut,dd=v=>dateOnly(v);
  $('degel-tag').textContent=on?'Dégel en cours':soon?'Dégel à venir':'Hors période de dégel';$('degel-tag').className='tag '+(on?'red':soon?'amber':'green');
  $('degel').innerHTML=(on?'<b>Charges réduites pour les camions</b> jusqu’au '+esc(dd(g.fin)):soon?'Prochaine période de dégel : du <b>'+esc(dd(g.debut))+'</b> au <b>'+esc(dd(g.fin))+'</b>':'Dernière période de dégel : du '+esc(dd(g.debut))+' au '+esc(dd(g.fin))+'. Le MTQ publie la prochaine au début de mars')+' ('+esc(g.zone||'')+(g.partie?', '+esc(g.partie):'')+'). <a href="'+esc(g.source)+'" target="_blank" rel="noopener">Détails MTQ ↗</a>';
 }else{$('degel-tag').textContent='Dégel';$('degel').textContent='Période de dégel non publiée.'}
 const per=t=>t.debut?esc(dateOnly(t.debut.slice(0,10)))+' → '+esc(dateOnly(t.fin.slice(0,10))):'—';
 $('travaux-rows').innerHTML=tw.map(t=>'<tr><td><b>'+esc(t.travaux||'Travaux')+'</b><small>'+(t.route?'Route '+esc(t.route)+' · ':'')+n(t.km)+' km</small></td><td>'+esc(t.lieu||'')+'</td><td>'+(t.charge?'<span class="tag amber">'+esc(t.charge)+'</span> ':'')+esc(t.entrave||'')+'</td><td>'+per(t)+'</td></tr>').join('')||'<tr><td colspan="4" class="muted">Aucun chantier routier publié dans le secteur.</td></tr>';
}
// Aperçu rapide (haut de l'onglet Déneigement) : conditions actuelles, plan, radar, neige heure par heure, routes, 5 jours.
// Prévisions jour (6 h-18 h) et nuit (18 h-6 h) : médianes des modèles pondérées par leur fiabilité mesurée
// (neige : confiance, pluie : confiance_pluie); probabilité : MétéoMédia et Environnement Canada par période.
function halves(){const tz='America/Toronto',key=t=>new Intl.DateTimeFormat('en-CA',{timeZone:tz}).format(t),hr=t=>+new Intl.DateTimeFormat('en-CA',{timeZone:tz,hour:'numeric',hourCycle:'h23'}).format(t);
 const slot=t=>{const u=t-6*3600e3;return key(u)+'|'+(hr(u)<12?'jour':'nuit')},acc={},now=Date.now();
 const wmed=a=>{a=a.filter(p=>p[0]!=null&&p[1]>0).sort((x,y)=>x[0]-y[0]);const tot=a.reduce((t,p)=>t+p[1],0);let c=0;for(const [v,w] of a){c+=w;if(c>=tot/2-1e-9)return v}return null};
 for(const m of state.models||[]){if(m.status!=='ok')continue;const per={},hasP=(m.hours||[]).some(h=>h.precip_mm!=null);
  for(const h of m.hours||[]){const t=Date.parse(h.time);if(t<now-3600e3)continue;const k=slot(t),e=per[k]=per[k]||{hi:-99,lo:99,sn:0,rn:0,n:0};
   if(h.temp!=null){e.hi=Math.max(e.hi,h.temp);e.lo=Math.min(e.lo,h.temp)}e.sn+=h.snow_cm||0;e.rn+=h.snow_cm>0?0:h.precip_mm||0;e.n++}
  for(const k in per){const e=per[k];if(e.n<3)continue;const x=acc[k]=acc[k]||{hi:[],lo:[],sn:[],rn:[],pop:[],txt:[]};
   if(e.hi>-99){x.hi.push([e.hi,1]);x.lo.push([e.lo,1])}x.sn.push([e.sn,m.confiance?.poids??1]);if(hasP)x.rn.push([e.rn,m.confiance_pluie?.poids??1])}}
 const pct=v=>v==null?null:parseFloat(String(v));
 for(const s of state.sources||[])for(const p of s.periods||[]){const v=pct(p.pop);let k;
  if(p.start_h!=null){const t=Date.parse(p.date+'T'+String(p.start_h).padStart(2,'0')+':00:00-05:00');k=slot(t+3600e3)}
  else k=p.date+'|'+(/soir|nuit/i.test(p.label)?'nuit':'jour');
  const x=acc[k]=acc[k]||{hi:[],lo:[],sn:[],rn:[],pop:[],txt:[]};if(v!=null&&!isNaN(v))x.pop.push(v);if(p.text)x.txt[s.id==='eccc'?'unshift':'push'](p.text)}
 // Probabilité précise (au pour cent) : NBM sur 12 h, 7 h-19 h et 19 h-7 h; sinon MétéoMédia / Environnement Canada (par 10 %).
 const nbmPop={};for(const w of state.pop12?.fenetres||[])nbmPop[slot(Date.parse(w.debut)+3600e3)]=w.pop;
 const out={};for(const k in acc){const x=acc[k];out[k]={hi:wmed(x.hi),lo:wmed(x.lo),sn:wmed(x.sn),rn:wmed(x.rn),pop:nbmPop[k]??(x.pop.length?Math.round(Math.max(...x.pop)):null),txt:x.txt[0]||''}}
 return out}
const MOON='<svg viewBox="0 0 48 48" aria-hidden="true"><path d="M30 8a16 16 0 1 0 12 26A14 14 0 0 1 30 8z" fill="#FFD166"/></svg>';
const finalLbl=f=>f.type==='reprise_matin'?'Reprise le matin':f.type==='deuxieme_tournee'?'2e tournée':'Nettoyage final';
function renderQuick(){
 const e=state.sources.find(s=>s.id==='eccc'&&s.status==='ok'),cur=e?.current||{},h0=(e?.hourly||[])[0];
 const v=x=>x?.value?.fr??x?.value?.en??x?.value??null,temp=v(cur.temperature),chill=v(cur.windChill),wind=v(cur.wind?.speed),cond=h0?.condition||'';
 $('now-temp').textContent=temp==null?'—':(Math.round(temp)+0)+' °C';$('now-cond').textContent=cond||'—';
 $('now-extra').textContent=[chill!=null&&chill<temp-1?'ressenti '+Math.round(chill)+' °C':'',wind!=null?'vent '+Math.round(wind)+' km/h':''].filter(Boolean).join(' · ');
 $('now-icon').innerHTML=cond?symbol([riskOf(cond)]):'';
 // Plan de sortie
 const p=(state.plan||[]).find(x=>x.statut==='sortie'||x.statut==='possible');
 if(p){const go=p.statut==='sortie';
  $('q-plan').innerHTML='<div class="section-heading"><h2>Plan de sortie</h2><span class="tag '+(go?'amber':'')+'">'+(go?'Sortie prévue':'Sortie possible')+'</span></div><div class="q-big">'+hhmm(p.depart)+'</div><div class="q-big-sub">'+(p.mode==='soir'?'Passage rapide en fin de journée':'Départ estimé')+' · '+esc(dayOf(p.depart))+(p.final?.type==='reprise_matin'?' · reprise le lendemain '+hhmm(p.final.heure):'')+'</div><div class="q-figs"><div><strong>'+n(p.fourchette_cm[0])+'–'+n(p.fourchette_cm[1])+' cm</strong><span>Neige prévue</span></div><div><strong>'+n(state.plan_config?.seuil_cm||5)+' cm</strong><span>Seuil au sol</span></div><div><strong>'+(p.echeance?hhmm(p.echeance):'≈ '+hhmm(p.fin_tournee))+'</strong><span>'+(p.echeance?'Commercial prêt':'Fin de tournée')+'</span></div></div><button class="linkish" data-open="plan">Plan détaillé ↗</button>';
 }else $('q-plan').innerHTML='<div class="section-heading"><h2>Plan de sortie</h2><span class="tag green">Aucune sortie</span></div><div class="q-big q-calm">—</div><div class="q-big-sub">Aucune sortie prévue dans les 72 prochaines heures</div><button class="linkish" data-open="plan">Plan détaillé ↗</button>';
 // Neige heure par heure, 12 prochaines heures
 const hs=(state.hourly_snow||[]).filter(h=>Date.parse(h.time)+3600000>Date.now()).slice(0,12),max=Math.max(0.5,...hs.map(h=>h.snow_cm));
 $('q-hourly').innerHTML=!hs.length?'<p class="muted">Aucune série horaire disponible.</p>':hs.every(h=>h.snow_cm<0.05)?'<p class="q-none">Pas de neige prévue dans les 12 prochaines heures.</p>':'<div class="q-bars-row">'+hs.map(h=>'<div class="q-bar" title="'+esc(hhmm(h.time)+' · '+n(h.snow_cm)+' cm/h')+'"><em>'+(h.snow_cm>=0.05?n(h.snow_cm):'')+'</em><i style="height:'+Math.round(h.snow_cm/max*100)+'%"></i><small>'+new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',hour:'numeric',hourCycle:'h23'}).format(new Date(h.time))+' h</small></div>').join('')+'</div>';
 // Routes
 const r=state.routes,g=r?.resume?.gravite??null;
 $('q-roads-tag').textContent=g==null?'—':GRAV[g][0];$('q-roads-tag').className='tag '+(g==null?'':GRAV[g][1]);
 $('q-roads').textContent=r?(r.resume?.texte||'État non publié')+' · '+(r.evenements?.length||0)+' avertissement'+((r.evenements?.length||0)>1?'s':'')+' · '+(r.cameras?.length||0)+' caméras à proximité':'Données routières non disponibles.';
 // Prévisions 5 jours
 const r0=x=>x==null?null:Math.round(x)+0; // +0 : pas de « -0 »
 const H=halves(),hcell=(d,h)=>{const x=H[d.date+'|'+h];if(!x)return '<div class="q-half past"><em>'+(h==='jour'?'Jour':'Nuit')+'</em><span class="muted">—</span></div>';
  const sn=x.sn??0,rn=x.rn??0,t=h==='jour'?x.hi:x.lo,ico=sn>=0.5&&rn>=0.5?ICONS.mix:sn>=0.5?ICONS.snow:rn>=0.5?ICONS.rain:(()=>{const r=x.txt?riskOf(x.txt):(x.pop??0)>=50?'Nuage':'Soleil';return r==='Soleil'?(h==='nuit'?MOON:ICONS.sun):symbol([r])})();
  const q=sn>=0.5?'❄ '+n(Math.round(sn*2)/2)+' cm':rn>=0.5?n(Math.round(rn))+' mm':'';
  return '<div class="q-half"><em>'+(h==='jour'?'Jour':'Nuit')+'</em><span class="q-ico">'+ico+'</span><strong>'+n(r0(t))+'°</strong><small class="pop">💧 '+(x.pop!=null?x.pop+' %':'—')+'</small><small class="q-qty">'+(q||'&nbsp;')+'</small></div>'};
 $('q-days').innerHTML=(state.consensus||[]).slice(0,5).map(d=>'<div class="q-day"><b>'+esc(new Intl.DateTimeFormat('fr-CA',{timeZone:'America/Toronto',weekday:'short',day:'numeric'}).format(new Date(d.date+'T12:00:00-05:00')))+'</b>'+hcell(d,'jour')+hcell(d,'nuit')+'</div>').join('');
 // Épandage : verglas confirmé, ou pluie / fonte puis regel (scripts/epandage.py)
 const ep=state.epandage,epBox=$('q-epand'),mo=new Date().getMonth()+1,hiver=mo>=11||mo<=4;
 epBox.hidden=!(ep?.length||(hiver&&ep));
 if(!epBox.hidden)epBox.innerHTML='<div class="section-heading"><h2>Épandage</h2><span class="tag '+(ep.length?'amber':'green')+'">'+(ep.length?ep.length+' sortie'+(ep.length>1?'s':'')+' prévue'+(ep.length>1?'s':''):'Rien de prévu')+'</span></div>'+(ep.length?'<ul class="ep-list">'+ep.map(it=>'<li><div class="ep-when"><strong>'+hhmm(it.depart)+'</strong><span>'+esc(dayOf(it.depart))+'</span></div><div class="ep-what"><b>'+esc(it.produit)+'</b><span>'+esc(it.raison)+(it.echeance?' · prêt pour '+hhmm(it.echeance):'')+(it.temp_min_c!=null?' · min. ≈ '+n(r0(it.temp_min_c))+' °C':'')+(it.avec_deneigement?' · avec la tournée de déneigement':'')+'</span></div></li>').join('')+'</ul>':'<p class="muted">Pas de verglas confirmé ni de regel après pluie ou fonte dans les 72 prochaines heures.</p>')+'<p class="ep-rule muted">'+esc(state.epandage_config?.produit||'Sel + calcium')+' jusqu’à '+n(state.epandage_config?.limite_sel_calcium_c??-18)+' °C, abrasif plus froid.</p>';
 bindOpeners();initMini();
}
let mini=null,miniLayer=null;
function initMini(){
 if(typeof L==='undefined'||$('operations').hidden)return;
 const m=new Date().getMonth()+1,layer=m>=11||m<=4?'RADAR_1KM_RSNO':'RADAR_1KM_RRAI';
 if(!mini){mini=L.map('mini-map',{zoomControl:false,attributionControl:false,dragging:false,scrollWheelZoom:false,doubleClickZoom:false,touchZoom:false,boxZoom:false,keyboard:false}).setView([46.214,-70.486],8);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:12}).addTo(mini);
  L.circleMarker([46.214,-70.486],{radius:6,color:'#fff',weight:2,fillColor:'#FFB81C',fillOpacity:1}).addTo(mini);
  mini.on('click',()=>tab('radar'))}
 if(miniLayer)mini.removeLayer(miniLayer);
 miniLayer=L.tileLayer.wms(GEOMET,{layers:layer,format:'image/png',transparent:true,version:'1.3.0',opacity:.8,t:Date.now()}).addTo(mini);
 setTimeout(()=>mini.invalidateSize(),50);
}
function openGroup(name,toggle=true){
 const groups=[...document.querySelectorAll('[data-group]')],cur=groups.find(g=>!g.hidden)?.dataset.group,show=toggle&&cur===name?null:name;
 groups.forEach(g=>g.hidden=g.dataset.group!==show);
 document.querySelectorAll('.sub-tabs [data-open]').forEach(b=>{b.classList.toggle('active',b.dataset.open===show);b.setAttribute('aria-selected',b.dataset.open===show)});
 if(show){const el=document.querySelector('[data-group="'+show+'"]');setTimeout(()=>el.scrollIntoView({behavior:'smooth',block:'start'}),30)}
}
function bindOpeners(){document.querySelectorAll('[data-open]').forEach(b=>{if(!b.dataset.bound){b.dataset.bound=1;b.addEventListener('click',()=>{if($('operations').hidden)tab('operations');openGroup(b.dataset.open,b.closest('.sub-tabs')!=null)})}})}
$('nav-more').addEventListener('click',()=>{const o=!$('nav').classList.contains('open');$('nav').classList.toggle('open',o);$('nav-more').setAttribute('aria-expanded',o)});
document.querySelectorAll('#nav [data-tab]').forEach(b=>b.addEventListener('click',()=>{$('nav').classList.remove('open');$('nav-more').setAttribute('aria-expanded','false')}));
bindOpeners();
tab(homeTab());
load();
