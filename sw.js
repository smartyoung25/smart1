/* KAASA Farmingsight — Service Worker (오프라인 캐시)
 * HTML 화면: network-first → 항상 최신, 오프라인 시 캐시 폴백 (묵은 화면 방지)
 * 정적(CSS/JS/아이콘): stale-while-revalidate → 빠름 + 백그라운드 갱신
 * API(/api/): network-first
 */
const CACHE = 'kaasa-smartos-v89';  // ★ v89: E2E 경제모델 SSOT — 수확량 단일함수(get_yield_forecast, /harvest·/revenue 통일)·단가 통일(erp_calculator→get_price_with_fallback)·매출=수량×단가 파생(디커플 제거)·비용 시즌화. C3-A/B·C5-1/3 해소.  // ★ v88: E2E 2026-08-07 격리버그 수정 — G4-1(/erp/realtime get_farm_meta→_require_farm, 전농가 딸기폴백 해소)·F4-2(관개량 ×1000→×10000 10배오류)·G3-4(Period 완료판정 순서기반, parseFloat NaN 고착 해소)  // ★ v87: J 상태배선 — sf_correction(PDCA 보정) 홈 예측·매출 반영(루프 완결)·보정배지, c0_signup 실가입 시 sf_role/sf_signup_role 설정  // ★ v86: D 지표 정합 — VPD 적정밴드 0.8~1.2 전 화면 통일(c3·g2·g3·guide·data.js·decision_card), DLI g2 작목별화, 배액률 문서 정합  // ★ v85: HIGH 기능불능 수정 — 재학습 승인 body 스키마(console_model), + 백엔드 PDCA Do env·What-if 델타·활동요약 테스트기록 제외  // ★ v84: CRIT-A 인증 견고화 — apiFetch 토큰 매호출 재조회+401 데모토큰 재발급·1회 재시도, wsConnect 최신토큰, SW /api/ 200게이트(만료토큰 캐시재생 차단)  // ★ v83: 화면감사 정직화 — 데모403 거짓성공(C16 일괄·C21 신청) 정정·작목 폴백('오이/토마토'→실제작목/작목미지정, C3처방·C12·C5·G5)  // ★ v82: 푸터 문의 이메일(iiam@iiam.co.kr) 표기 — index·intro·console  // ★ v81: G7 오늘의 작업(일일·주간 작업추천 — P1~P6 Period·환경 전략표 편차·근거 제시)  // ★ v80: C13 지식베이스 연결(교재735+규칙15=750청크 BM25 검색·근거 프롬프트 주입·출처 쪽수 표기)  // ★ v79: C13 챗봇 정직화(거짓 RAG·출처 표기 제거·폴백 모드 배지)  // ★ v78: 브랜드 리네임(KAASA smartfarmingsight → KAASA Farmingsight)  // ★ v77: 여정감사 2차(데모 온보딩 안내·작목 단일출처·C10/F6/F5 정직표기)  // ★ v76: 여정 감사 수정(거짓성공 5곳 서버기록·BEP 복구·자격증명 제거·생산→경영 다리 복구·병해 단계 편입)  // ★ v75: 가치사슬 흐름 연속화(도메인 간 넘김·14개 단계화면 스테퍼 자동주입)  // ★ v74: 데스크톱 반응형(inline480 무력화·좌측 사이드네비 주입·다열 그리드, 모바일 회귀0)  // ★ v73: P0 모델캐시초기화·ERP404수정·DB헬스경보 / P1 F8재배치·C12가입상태·C17컨설팅CTA·C20→F8드릴다운  // ★ v72: C1 중간저장·복원·힌트·인라인검증 / auth 13항목 / C3 온보딩 넛지  // ★ v68: 터치타겟 44px 통일·r.ok가드·Mock텍스트 제거  // ★ v67: c5_erp 소득구조폭포수+농가조사표 13항목 비용상세  // ★ v66: c1_setup 기타직접입력·c16 빠른일괄등록·c21 장비등록선행체크·c24 시공업체입력·f1 팜맵자동연동  // ★ v65: c25_pdca 로드 중 고착 수정(_apiFetch r.ok·token guard·catch 전면);  // ★ v63: C25 PDCA 운영관리 (적기적작 3대 지수 + PDCA 루프 + 임계값 알림);  // ★ v61: c2_consent ?next= 안전 경로검증(오픈리다이렉트·주입 차단)';  // v60: C17 평가카드;  // v59: 온실 순차흐름 CTA;  // v58: 회원가입 흐름 일관화';  // v57: C16 평가요약';  // v56: C16 흐름 직관화';  // v55: 업로드 자동 재분류';  // v54: C16 공종별 분류 재설계';  // v53: C24 온실 시공업체 찾기';  // v52: C16 공식 기자재 DB 자동완성';  // v51: C16 장비추가 개선';  // v50: C6 입력 데이터 품질(드리프트 신호) 패널';  // ★ v49: C13 AI비서 입력 이상치 선제 알림';  // ★ v48: 입력 이상치 자동 플래그(data_anomaly)→C17 데이터 품질 점검';  // ★ v47: F4 노지 관개량 이상치 경고';  // ★ v46: G3 관수 입력 이상치 경고(EC·pH 범위 가드)';  // ★ v45: G2 환경 입력 이상치 경고(허용범위 차단·정상범위 확인)';  // ★ v44: G2 환경 입력 이력(수정 추적) 기록·표시';  // ★ v43: G2 환경 실측값 입력·수정(수동 입력→화면 반영)';  // ★ v42: G2 환경 출처배지 정직화(등록 센서 연동 반영)·중복배지 정리';  // ★ 버전 변경 시 구 캐시 자동 삭제 (v41: C16 표준변수 한글 라벨)
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

  // API: network-first. ★ 200만 캐시 — 401/500(만료토큰·오류)을 캐시해 오프라인에 재생하면
  //   토큰 만료 후에도 낡은 인가 응답을 되돌려주는 문제. HTML/정적 분기와 동일하게 200 게이트.
  if (url.pathname.startsWith('/api/')) {
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
