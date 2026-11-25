/* Service worker: la app queda guardada para abrirla sin internet después de la primera carga. */
const CACHE = "destiny-dbm-v1";
const SHELL = ["./", "index.html", "static/app.css", "static/app.js", "bridge.js", "pyworker.js",
  "py/archive.py", "py/database.py", "py/team_assets.py", "py/bridge.py",
  "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === location.origin;
  const isPyodide = url.hostname === "cdn.jsdelivr.net" && url.pathname.startsWith("/pyodide/");
  if (!sameOrigin && !isPyodide) return;
  if (isPyodide) {   // el motor Python no cambia: primero caché
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res && (res.ok || res.type === "opaque")) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    })));
    return;
  }
  // archivos propios: primero red (para recibir actualizaciones), caché si no hay internet
  event.respondWith(fetch(req).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req, { ignoreSearch: true })));
});
