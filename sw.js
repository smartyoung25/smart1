/* KAASA smartfarmingsight — Service Worker (오프라인 캐시)
 * HTML 화면: network-first → 항상 최신, 오프라인 시 캐시 폴백 (묵은 화면 방지)
 * 정적(CSS/JS/아이콘): stale-while-revalidate → 빠름 + 백그라운드 갱신
 * API(/api/): network-first
 */
const CACHE = 'kaasa-smartos-v54';  // ★ v54: C16 공종별 분류 재설계(대분류→기종)+평가완료 카탈로그 종합등급 자동완성';  // v53: C24 온실 시공업체 찾기';  // v52: C16 공식 기자재 DB 자동완성';  // v51: C16 장비추가 개선';  // v50: C6 입력 데이터 품질(드리프트 신호) 패널';  // ★ v49: C13 AI비서 입력 이상치 선제 알림';  // ★ v48: 입력 이상치 자동 플래그(data_anomaly)→C17 데이터 품질 점검';  // ★ v47: F4 노지 관개량 이상치 경고';  // ★ v46: G3 관수 입력 이상치 경고(EC·pH 범위 가드)';  // ★ v45: G2 환경 입력 이상치 경고(허용범위 차단·정상범위 확인)';  // ★ v44: G2 환경 입력 이력(수정 추적) 기록·표시';  // ★ v43: G2 환경 실측값 입력·수정(수동 입력→화면 반영)';  // ★ v42: G2 환경 출처배지 정직화(등록 센서 연동 반영)·중복배지 정리';  // ★ 버전 변경 시 구 캐시 자동 삭제 (v41: C16 표준변수 한글 라벨)
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

  // network-first 대상: HTML 화면 + 공용 클라이언트 JS/CSS(/components/).
  //   components/* 도 network-first로 둬야 배포 직후 data.js·base.css 수정이 즉시 반영됨
  //   (구: SWR → 첫 로드는 구 data.js 서빙 → 게이트/등급/관수 수정이 한 박자 늦게 적용되던 문제).
  const isHTML = req.mode === 'navigate'
    || (req.headers.get('accept') || '').includes('text/html')
    || url.pathname.endsWith('.html')
    || url.pathname.startsWith('/components/')
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
