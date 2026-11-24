// Funciona sem internet: guarda o app no celular. Sempre tenta a versão nova primeiro.
const C="trovia-v1";
const BASE=["./","./index.html","./manifest.webmanifest","./icon-192.png","./icon-512.png","./apple-touch-icon.png"];
self.addEventListener("install",e=>{ e.waitUntil(caches.open(C).then(c=>c.addAll(BASE))); self.skipWaiting(); });
self.addEventListener("activate",e=>{ e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch",e=>{
  const u=new URL(e.request.url); if(e.request.method!=="GET") return;
  const proprio=u.origin===location.origin, leaflet=u.host==="cdnjs.cloudflare.com";
  if(!proprio && !leaflet) return; // IA, mapas e alertas oficiais sempre pela internet
  e.respondWith(fetch(e.request).then(r=>{ if(r.ok||r.type==="opaque"){ const cp=r.clone(); caches.open(C).then(c=>c.put(e.request,cp)); } return r; })
    .catch(()=>caches.match(e.request,{ignoreSearch:true}).then(m=>m||(e.request.mode==="navigate"?caches.match("./index.html"):undefined))));
});

// Toque no aviso: abre o app (ou traz para frente) na tela certa
self.addEventListener("notificationclick",e=>{
  e.notification.close(); const url=(e.notification.data&&e.notification.data.url)||"./";
  e.waitUntil(clients.matchAll({type:"window",includeUncontrolled:true}).then(cs=>{
    for(const c of cs){ if("focus" in c){ c.postMessage({abrir:url}); return c.focus(); } }
    return clients.openWindow(url);
  }));
});
