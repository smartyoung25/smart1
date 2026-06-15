# smart_farm 세션 아카이브 — 2026년 6월
> 이 파일은 자동으로 읽히지 않음. 참조 필요 시 명시적으로 요청할 것.
> grep으로 검색: grep -n "키워드" archive/SESSIONS_2026-06.md

---

## 2026-06-11: 리브랜딩·인증·전략표·대시보드 일원화

**제품명**: KAASA SmartOS → KAASA smartfarmingsight 전면 변경
**도메인**: https://farmingsight.org (Cloudflare Named Tunnel)

### 완료 작업
- 브랜드명 전 화면 122곳 치환 (기능식별자 /smartos·kaasa-smartos 터널·SW키는 보존)
- 첫화면(/intro) 리디자인 + 전역 .section-label 강조바 (41화면)
- 다크/라이트 테마 토글: base.css html[data-theme="dark"] + data.js toggleTheme() + localStorage sf_theme
- 전역 플로팅 버튼 (홈·도움말) data.js _installFab()
- 회원가입 이메일·전화번호 필수+형식검증. phone 폴백: data/user_contacts.json
- 비밀번호 찾기/재설정: /password/forgot·/reset + 토큰(data/password_resets.json, 30분) + api/services/mailer.py(SMTP)
- 신규 screens/c0_reset.html
- 공개 데모 실가입 허용
- PUBLIC_DEMO 쓰기 허용목록 확대 (_WRITE_ALLOW, _WRITE_ALLOW_SUFFIX, _WRITE_ALLOW_CONTAINS)
- /api/admin/* 관리자 쓰기·조회는 여전히 403
- C1 재배방식 분류 정정 (양액 독립항목 제거)
- 목표 수확량 → 면적당(kg/10a), 총량 자동환산
- 데이터동의 저장: GET/POST /consent (farmer.py)
- 신규 C21 c21_apply.html (연동·서비스 신청)
- G2 환경관리 전략표: api/services/climate_plan.py
  - 2축: 행=생육시기 × 열=하루4구간, 셀=온도/습도/CO₂(VPD자동)
  - GET/POST /environment/climate-plan·/active·/evaluate
  - Priva 광연동승온·HNT·Plant Empowerment VPD밴드 벤치마크
  - evaluate()가 전략표 목표 대비 실측편차로 처방생성
  - sun_times() Open-Meteo 무키 / record_daily_temp HNT 보정
- PC 대시보드 ↔ 모바일 값 불일치 통일:
  - DLI PAR계수 4.57 / VPD밴드 0.4·0.6 / 배액률 norm[20,35]·crit[15,45]
  - C6 드리프트모니터링+M1~M5 / G4 What-if·SFROP / G2 권고빈도
  - 루트 /·/dashboard/* → /intro 307 리다이렉트
- deploy/cloudflare/watchdog.ps1: uvicorn+cloudflared 자동재기동 + Mutex 단일인스턴스 가드
- SW 캐시 v16

### 미완료 (사용자 직접 조치 필요)
- SMTP: .env SMTP_USER·SMTP_PASSWORD 미설정 (Gmail 앱비번 필요)
- ANTHROPIC_API_KEY 미설정 → 챗봇 규칙기반 폴백
- 터널 부팅영속: cloudflared service install (선택)
- 잔여파일: dashboard/index.html.tmp1, 루트 tmp_*.py/png (내가 안 만든 파일, 보류)

---

## 2026-06-10: 데모 충실화·왜곡교정·노지 실데이터 노출

### 완료 작업
- 보고서(c14/c17/c20) 배경색 #5a6678→#e7edf3
- F1 노지 현장컨설팅 배너 (C17·C18·C19·C4)
- 네비게이터 섹션 5그룹 재정리 (38카드 보존)
- C20 왜곡 교정: build_overview 실데이터(725농가·이상31.3%)로 교체
- data.js _DEMO_FARMS 작물별 전환기 (오이001·방울002·딸기003·완숙004·파프리카·제주)
- _syncFarmSelectors() 전화면 #farmSel 통일
- C6 모델 임계점·최적모델 노출: 배포게이트(MAPE≤35%·R²≥0) + 챔피언/챌린저
- M2 게이트표: 딸기·오이·완숙·파프리카 통과 / 방울48.6%·참외63.9% 폴백
- 연합학습(federated-lite): pipeline/federated/ + api/routers/federated.py
- _require_farm 레지스트리 meta 캐싱 버그 수정 (18개 사이트 빈meta 해결)
- _real_parcels_lookup 읍면명↔시군구키 불일치 폴백 추가
- ERA5 외부기온 보강: temp_external 결측20% → 딸기 R² 0.192→0.295(+0.103), MAPE 20.8→17.8%
  - 원칙: LOYO CV baseline 대비 개선시만 채택, 미달 즉시 롤백
  - 결론: ERA5 외부기온은 겨울딸기에만 유효 (타작물 효과 없음)
- AI비서(C13) 데모 POST /chat 허용
- 회원가입(C0) 유통전문가 역할 추가 (5역할), 역할별 라우팅
- screens/help.html 앱 내 도움말
- DecisionDeck 거짓성공 제거
- SW 캐시 HTML network-first + CACHE v3
- v1.7 릴리스: 4.5MB·988파일·41화면
- docs/USER_MANUAL.md (17장) · docs/DEMO_GUIDE_BY_CROP.md
- ERA5 climatology: api/services/climatology.py + GET /environment/climatology?crop=
  - 26작물 월별 평년값 (기온·일사·강수·GDD)
  - G2·F3·F8 3화면 통합
  - F8 이상기상 감지 시 알림 심각도 상향

---

## 2026-06-09: 실데이터·챗봇·릴리스·노지·역량·진단

### 제주 실데이터 주입
- 흙토람 토양검정 13,842필지 → /field/soil naas_soil_real
- 팜맵 276,491필지 → /field/parcels farmmap_real
- 소득조사 102농가 → /benchmark 실비교군
- scripts/import_real_{soil,parcels,income,pest}.py, api/data/real/*.json

### 화면 시각화 10건 (SVG/CSS)
- C3 우수농가바·실데이터배지 / C17 6대영역 레이더 / F8 NDVI 히트맵
- G3 일일WC곡선 / C14 전월대비 다이버징 / G2 온습도·VPD추이
- G6 신뢰구간밴드 / F3 16일 기온·강수 / G4 초장추세

### 프레임워크 통일
- base.css: 차트 팔레트 토큰 --chart-hot/cool/good/warn/rain
- :focus-visible·prefers-reduced-motion·.sum-tab 40px
- C20 다중농가 클러스터 관제(723농가)+보고서PDF+일괄알림

### 노지 클러스터 작황 모니터링 (F8)
- api/services/field_cluster.py + GET /field/cluster
- f8_cluster.html: 작황hero·균일도·기상스트레스·NDVI그리드·위치특정알림
- 검수: 경남창녕 4필지 2.3ha, 2번필지 NDVI0.49 Δ-29.7% 생육저조 알림

### 역량별 핵심 서비스 (C19)
- api/services/capability_router.py: 4단계 판정 (기반구축/데이터정착/정밀제어/경영고도화)
- GET /capability + c19_capability.html

### 진단 이력·추세
- GET /diagnosis/history + POST /diagnosis/snapshot
- C17 추세 스파크라인 (52→61→68→74)

### 16일 장기예보
- api/services/extended_weather.py: Open-Meteo 16일·6h캐시·재해경보
- GET /environment/weather/extended + F3 스트립

### 현장컨설팅 종합진단 (C17+C18)
- api/services/consulting_diagnosis.py: 6대 도메인 점수
- GET/POST /diagnosis/checklist (30항목)
- C18 c18_checklist.html 신규

### 외부연동·챗봇
- docs/INTEGRATION_GUIDE.md + check_integrations.py
- build_farm_context 진단·역량·작황 주입
- v1.3 릴리스: 39화면·71파일

### 사용자 여정 정합
- C1 저장 CTA 분기 (노지→F8/F1, 온실→C16)
- data.js _renderStratBand() 경영전략 교차연결

---

## 2026-06-04: 사업계획서 정합·종합진단·인트로

### Priva 관수 정밀화
- data.js IRRIGATION_START·IRRIGATION_STRUCTURE
- irrigation_adapter dryback_night_pct / IrrigationPayload period le=6

### C17 시스템 종합진단 신규
- GET /diagnosis: 장비·연동·데이터·운영·캘리브 5영역 점수 + ROI

### 인트로·메뉴
- screens/intro.html + /intro 라우트
- 전역 기능형 드로어 data.js 자동주입 (33화면)
- 버그: intro CTA 상대경로 404 / ../index.html → /index.html

---

## 2026-06-02: 운영기록·기자재

### RecordSheet 폐루프
- components/record_sheet.js
- POST /activity: F4·F6·F7·G2·G3·G4·F3

### 시설 기자재 통합 (C16)
- docs/EQUIPMENT_INTEGRATION.md + api/data/equipment_schema.json (8군·표준변수22)
- screens/c16_equipment.html
- GET /equipment/schema · GET/POST/DELETE /equipment

---

## 2026-06-01: 초기 28화면 완성

### 완료된 화면
- 공통 C (13): C0~C12 (C3·C4·C5·C6·C12 실연동)
- 온실 G (6): G1~G6 전부 실연동
- 노지 F (7): F1·F3·F4·F6·F7 실연동 / F2·F5 Mock
- 개요: overview·flow
- 네비게이터: index.html

### 작물 12종
딸기·방울토마토·완숙토마토·참외·파프리카·오이 + 제주7종(감귤·월동무·당근·양배추·브로콜리·마늘·양파)

### 정책 대응 (스마트농업법)
- 6대 영역 통합 모니터링 / 9대 성과지표
- 월간 경영성과 리포트 / 교육과정·이수율
- 이행→축적→학습→환원 폐루프

### 주요 백엔드
- GET /report/monthly, POST /activity, GET /activity/summary
- GET /field/soil, /field/parcels
- kamis_fetcher ITEM_CODES 제주7종

### 등급 차등 (tier_features.json)
- 레벨① 잠금/배지 / 레벨② tier_guard.js 오버레이 / 레벨③ /billing/* 402

### DecisionDeck (components/decision_card.{css,js})
- 심각도3중코딩+처방+신뢰도+원탭+신선도
- buildGreenhouse/buildField 빌더
- band_chart.js (g3 배액률 목표대 밴드) / device_alert.js (기기 알림 분리)
- F2 GIS peelable 레이어

---

## 미해결 Backlog (2026-06-01 기준, 현재도 유효 여부 확인 필요)
- C12 공동출하 화면 구현
- KAASA 실제 API 엔드포인트 확인
- 농진청 표준모델 JSON 수신 방법
- 실기기 MQTT 연결 테스트
- kaasa_smartos_mobile.html 분리 작업
