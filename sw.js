/* KAASA smartfarmingsight — Service Worker (오프라인 캐시)
 * HTML 화면: network-first → 항상 최신, 오프라인 시 캐시 폴백 (묵은 화면 방지)
 * 정적(CSS/JS/아이콘): stale-while-revalidate → 빠름 + 백그라운드 갱신
 * API(/api/): network-first
 */
const CACHE = 'kaasa-smartos-v30';  // ★ 버전 변경 시 구 캐시 자동 삭제 (v30: / 200 직접서빙·Breadcrumb·FAQ JSON-LD)
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

  // HTML 화면(네비게이션·.html·라우트): network-first → 항상 최신 (오프라인만 캐시)
  const isHTML = req.mode === 'navigate'
    || (req.headers.get('accept') || '').includes('text/html')
    || url.pathname.endsWith('.html')
    || ['/smartos', '/intro', '/index.html'].includes(url.pathname);
  if (isHTML) {
    e.respondWith(
      fetch(req).then(res => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // 정적 자산(CSS/JS/아이콘): stale-while-revalidate (빠름 + 백그라운드 갱신)
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
