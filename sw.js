/* KAASA SmartOS — Service Worker (오프라인 캐시)
 * 정적(HTML/CSS/JS/아이콘): cache-first → 오프라인에서도 화면 표시
 * API(/api/): network-first → 항상 최신, 실패 시 마지막 캐시 폴백
 */
const CACHE = 'kaasa-smartos-v1';
const CORE = [
  '/intro', '/index.html',
  '/components/base.css', '/components/data.js',
  '/components/decision_card.js', '/components/record_sheet.js',
  '/icon.svg', '/manifest.webmanifest',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE).catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;                       // 쓰기/텔레메트리는 통과
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;             // 외부(타일·CDN)는 통과

  // API: network-first
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // 정적: cache-first (+ 백그라운드 갱신)
  e.respondWith(
    caches.match(req).then(cached => {
      const net = fetch(req).then(res => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => cached);
      return cached || net;
    })
  );
});
