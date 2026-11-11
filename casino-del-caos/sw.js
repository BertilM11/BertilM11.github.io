/* Casino del Caos: guarda la app en el dispositivo para que abra sin internet.
   Al publicar cambios, subí el número de VERSION para que todos reciban la nueva versión. */
const VERSION = 'v4';
const CACHE = 'casino-del-caos-' + VERSION;
const ASSETS = [
  './', './index.html', './manifest.webmanifest', './cloud.js',
  './icons/icon-192.png', './icons/icon-512.png', './icons/icon-maskable-512.png', './icons/apple-touch-icon.png',
  './fonts/lilita-one-400.woff2', './fonts/nunito-700.woff2', './fonts/nunito-800.woff2', './fonts/nunito-900.woff2'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('casino-del-caos-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // La página: se intenta traer la versión más nueva; si no hay internet (o tarda), se usa la guardada.
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match('./index.html');
      const network = fetch(req).then((res) => {
        if (res.ok) cache.put('./index.html', res.clone());
        return res;
      });
      if (!cached) return network;
      try {
        return await Promise.race([network, wait(2500).then(() => { throw new Error('lento'); })]);
      } catch (e) {
        return cached;
      }
    })());
    return;
  }

  // Íconos y fuentes: primero lo guardado.
  event.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) caches.open(CACHE).then((cache) => cache.put(req, res.clone()));
      return res;
    }))
  );
});
