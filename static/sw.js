const CACHE_NAME = 'fitdesk-pro-v5';
const ASSETS_TO_CACHE = [
  '/',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  '/favicon.png'
];

self.addEventListener('install', function(event) {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(ASSETS_TO_CACHE).catch(function() {});
    })
  );
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE_NAME; }).map(function(k) { return caches.delete(k); })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function(event) {
  if (event.request.method !== 'GET') return;
  // Network-first for API & HTML so cloud sync is always fresh, fallback to cache if offline
  event.respondWith(
    fetch(event.request)
      .then(function(response) {
        if (response && response.status === 200 && event.request.url.indexOf('/api/') === -1) {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, cloned).catch(function() {});
          });
        }
        return response;
      })
      .catch(function() {
        return caches.match(event.request);
      })
  );
});
