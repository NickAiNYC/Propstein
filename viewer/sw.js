// PropStein Service Worker (offline shell only; market data always fails closed)
const CACHE_NAME = 'propstein-v201-player-card-hierarchy';
const STATIC_ASSETS = [
  '/index.html',
  '/style.css',
  '/app.js',
  '/style.css?v=2026_v201',
  '/app.js?v=2026_v198',
  '/js/today-schedule.js?v=2026_v199',
  '/js/sports/ufc.js?v=2026_v199',
  '/ufc.css?v=2026_v199',
  '/js/ufc-fighter.js?v=2026_v199',
  '/js/front-page.js?v=2026_v198',
  '/league-logos/nba.png',
  '/league-logos/nfl.png',
  '/league-logos/ufc.svg',
  '/league-logos/nhl.png',
  // v171: public verify landing assets (externalized from a336e2f inline blocks)
  '/verify-landing.css',
  '/verify-landing.js',
  '/verify-landing.css?v=2026_v189',
  '/verify-landing.js?v=2026_v179',
  '/js/sports/registry.js?v=2026_v179',
  '/js/sports/nfl.js?v=2026_v179',
  '/js/sports/nba.js?v=2026_v179',
  // brand marks: PropStein lighter ice-blue logo suite
  '/propstein-logo.png',
  '/propstein-logo.png?v=2026_v179',
  '/propstein-logo-dark.png',
  '/propstein-logo-dark.png?v=2026_v179',
  '/propstein-logo.svg?v=2026_v179',
  '/propstein-logo-dark.svg?v=2026_v179',
  '/propwire-logo.svg?v=2026_v179',
  '/propwire-logo-dark.svg?v=2026_v179',
  // v152: self-hosted sportsbook wordmark badges (same-origin, CSP 'self')
  '/books/draftkings.svg?v=v152',
  '/books/fanduel.svg?v=v152',
  '/books/betmgm.svg?v=v152',
  '/books/caesars.svg?v=v152',
  '/books/pinnacle.svg?v=v152',
  '/books/betrivers.svg?v=v152',
  '/books/fanatics.svg?v=v152',
  '/books/bet365.svg?v=v152',
  '/books/espnbet.svg?v=v152',
  '/books/circa.svg?v=v152',
  // v149 fix: this list previously referenced /manifest.json (never existed),
  // and addAll() is all-or-nothing — one 404 silently precached NOTHING.
  // Now every entry matches the exact busted URLs the pages request.
  '/site.webmanifest?v=2027_icon2',
  '/favicon.svg?v=2027_icon2',
  '/icon-192.png?v=2027_icon2',
  '/icon-512.png?v=2027_icon2',
  '/apple-touch-icon.png?v=2027_icon2'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache quotes, health state, picks, receipts, or other JSON/CSV data.
  // An offline research shell is useful; an offline price presented as current is not.
  if (/\.(?:json|csv)$/i.test(url.pathname)) {
    event.respondWith(fetch(event.request, { cache: 'no-store' }));
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .catch(() => caches.match('/index.html'))
        .then((response) => response || new Response('PropStein is offline. Live market data is unavailable.', {
          status: 503,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        }))
    );
    return;
  }

  const isStaticAsset = ['script', 'style', 'image', 'font', 'manifest'].includes(event.request.destination);
  if (!isStaticAsset) return;

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
      if (response && response.ok && response.type === 'basic') {
        const clone = response.clone();
        event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone)));
      }
      return response;
    }))
  );
});
