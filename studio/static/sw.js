// Manga Studio Service Worker
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Pass-through to local dynamic Flask server
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});
