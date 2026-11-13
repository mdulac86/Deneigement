const CACHE='deneigement-v9';
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['./','./index.html','./style.css','./app.js','./icon.svg','./logo-dulac.png'])));self.skipWaiting()});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(u.origin!==location.origin||e.request.method!=='GET')return;e.respondWith(fetch(e.request,{cache:'no-cache'}).then(r=>{if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return r}).catch(()=>caches.match(e.request).then(r=>r||Response.error())))});
self.addEventListener('push',e=>{let d={};try{d=e.data?e.data.json():{}}catch{d={title:'Déneigement',body:e.data?e.data.text():''}}
e.waitUntil(self.registration.showNotification(d.title||'Déneigement Saint-Prosper',{body:d.body||'',tag:d.tag,icon:'icon.svg',badge:'icon.svg',data:{url:d.url||'./'},requireInteraction:!!d.urgent}))});
self.addEventListener('notificationclick',e=>{e.notification.close();const url=(e.notification.data&&e.notification.data.url)||'./';
e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{for(const c of list){if('focus'in c){c.navigate&&c.navigate(url);return c.focus()}}return self.clients.openWindow(url)}))});
