# KAASA SmartOS v1.1 — 릴리스 노트

> 패키지: `KAASA_SmartOS_v1.1.zip` (203 KB) · 2026-06-04 · Farmingsight
> 진입: **http://localhost:8000/intro** (시스템 소개 랜딩) → 시작하기/둘러보기

## v1.0 → v1.1 변경 (이번 릴리스 추가분)
- **인트로 랜딩(/intro)**: 가치제안·5대문제·6층 아키텍처·CTA
- **전 화면 기능형 메뉴 드로어**: ≡ → 검색·등급칩·빠른이동22·농장전환·로그아웃 (data.js 자동주입)
- **C16 시설 기자재**(이기종 통합 매핑) · **C17 시스템 종합진단**(5영역 점수·ROI)
- **관수 P1~P6**(야간 dry-back 신설) + 프리바 시작조건·구조 + dryback 백엔드 적재
- **DecisionDeck**(오늘의 결정) C3·G1·F1 + band_chart·device_alert·F2 히트맵
- **운영기록 폐루프**(RecordSheet): 관개·방제·수확·생육·환경·작업계획·현장확인 → /activity
- **AI 비서**: LLM 키 없이도 실데이터 응답(관수·환경·에너지·수확·수익·병해·알림)
- **버그 수정**: 둘러보기 404 / 메뉴 401 / 회원가입 메시지 가림

## 구성 (34 화면 + 9 컴포넌트)
- `index.html`(네비게이터) · `screens/`(intro 포함 34) · `components/`(base.css·data.js + decision_card·record_sheet·tier_guard·band_chart·device_alert·equipment_link)
- `api/data/equipment_schema.json`·`tier_features.json`

## 성능 (Playwright 실측 · 2026-06-04)
| 페이지 | FCP | DOM Load | 리소스 | 전송량 | 정책목표(LCP<3.0s) |
|--------|-----|----------|--------|--------|--------|
| /intro | 480ms | 323ms | 1 | 14KB | 🟢 |
| /smartos | 440ms | 317ms | 1 | 14KB | 🟢 |
| c3_home | 480ms | 488ms | 8 | 64KB | 🟢 |
- 이전 Lighthouse(v1.0): 성능 100 · 접근성 94

## 등급 차등 (SaaS)
basic→smart→pro→enterprise · 메뉴/위젯 게이팅 · /billing 업그레이드 실연동

## 외부 키 주입 시 자동 전환
NAAS_SOIL/FARMMAP → F2·F5 실측 · ANTHROPIC_API_KEY → 챗봇 LLM · ERA5/KAMIS

## 검수
전 33화면 콘솔 에러 0 · 37경로·35링크 HTTP 200 · 인터랙션/쓰기경로 정상

## 실행
`python -m uvicorn api.main:app --port 8000` → `http://localhost:8000/intro`
