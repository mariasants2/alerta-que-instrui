// Funciona sem internet: guarda o app no celular. Sempre tenta a versão nova primeiro.
const C="aqi-v7";
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
