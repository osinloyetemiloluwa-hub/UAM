// v2: shell + Pyodide WASM cache. Never touches API/stream endpoints.
const SHELL = 'agent-shell-v3', WASM = 'pyodide-v1';
const API = ['/chat', '/files', '/runs', '/zip', '/profiles', '/models', '/health', '/selftest', '/phone/', '/ws'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/manifest.webmanifest'])).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k !== SHELL && k !== WASM).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET') return;
  // Pyodide runtime (~10 MB): cache-first so reloads never re-download it.
  if (url.hostname === 'cdn.jsdelivr.net' && url.pathname.includes('/pyodide/')) {
    e.respondWith(caches.open(WASM).then(async (c) => {
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok || res.type === 'opaque') c.put(req, res.clone()).catch(() => {});
      return res;
    }));
    return;
  }
  if (url.origin !== location.origin || API.some((p) => url.pathname.startsWith(p))) return;
  // HTML & app files: network-first, cache fallback for offline reload.
  e.respondWith(fetch(req).then((res) => {
    if (res.ok) caches.open(SHELL).then((c) => c.put(req, res.clone())).catch(() => {});
    return res;
  }).catch(() => caches.match(req).then((h) => h || caches.match('/nanomuse'))));
});
