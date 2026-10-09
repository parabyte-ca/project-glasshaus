// Project Glasshaus service worker: makes the app installable and lets the shell open offline.
// It caches only static files (the page shell, hashed /assets/, icons). API, SCIM, health and
// WebSocket traffic always goes to the network and is never stored, so no project data is cached.
const CACHE = 'glasshaus-shell-v2';
const SHELL = ['/', '/manifest.webmanifest', '/icon.svg', '/theme-init.js'];
const NETWORK_ONLY = /^\/(api|scim|healthz|readyz|nginx-health)(\/|$)/;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || NETWORK_ONLY.test(url.pathname)) return;

  if (request.mode === 'navigate') {
    // Network first so a new release shows at once; the cached shell only when offline.
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(CACHE).then((cache) => cache.put('/', copy));
          }
          return response;
        })
        .catch(() => caches.match('/').then((cached) => cached || Response.error())),
    );
    return;
  }

  if (url.pathname.startsWith('/assets/')) {
    // Hashed file names never change, so the cached copy is always right.
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              void caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  if (SHELL.includes(url.pathname)) {
    // Small static files: serve the cached copy and refresh it in the background.
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          const fresh = fetch(request)
            .then((response) => {
              if (response.ok) void cache.put(request, response.clone());
              return response;
            })
            .catch(() => cached || Response.error());
          return cached || fresh;
        }),
      ),
    );
  }
});

// Notifications pushed by the server (only when this device turned them on in Account settings).
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : '' };
  }
  const url =
    typeof data.url === 'string' && data.url.startsWith('/') && !data.url.startsWith('//') ? data.url : '/';
  event.waitUntil(
    self.registration.showNotification(data.title || 'Glasshaus', {
      body: data.body || '',
      tag: data.tag || undefined,
      icon: '/icon.svg',
      badge: '/icon.svg',
      data: { url },
    }),
  );
});

// Tapping a notification opens (or focuses) the app at its page.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const win of windows) {
        if (new URL(win.url).origin === self.location.origin && 'focus' in win) {
          return win.focus().then(() => ('navigate' in win ? win.navigate(target) : undefined));
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
