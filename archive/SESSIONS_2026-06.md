# smart_farm 세션 아카이브 — 2026년 6월

---

## 2026-06-18 세션 — 기자재·회원가입 흐름·보안·카탈로그

**커밋 범위**: 18457e5 → 22f1892

- 참조 DB v1: 스마트팜코리아 공식 DB — 자사제품 312·기업 623·시공업체 97
- C16 자동완성·분류 재설계: 대분류→기종, 카탈로그 종합등급 자동완성
- C24 시공업체 찾기: 도급순위·지역 검색
- 카탈로그 v2: 3071제품·공종별·11항목 5등급
- 업로드 자동 재분류: 견적서/시방서 → 카탈로그 매칭 → 등급·공종 부여
- OCR/PDF 매칭 정확도 개선 (제조사 정규화)
- 회원가입 흐름 단락 해소: farm_id 일관성·IDOR 차단·onboarding 라우팅
- c2_consent ?next= 보안: 오픈리다이렉트·주입 차단
- 카탈로그 공종 "기타" 2964→336건(89%↓)
- PII 제거: abc 테스트 계정·중복 farm_q93tkj 삭제
- Stop 훅 추가: 세션 종료 시 NEXT.md 자동 업데이트

---

## 2026-06-17 세션 — IPinsight 패턴 이식 + farm_002 데이터 통합

### 완료 작업
- **농업 명언 순환** (index.html): JS `Math.random()`으로 20개 농업·스마트팜 명언 중 1개 선택. 프로필 있으면 작물명으로 덮어씀 (기존 동작 유지)
- **.gitignore 신설**: `__pycache__`, `.env`, 텔레메트리 로그, 대용량 PPT/DOCX 제외
- **archive/ 신설**: IPinsight 세션 관리 체계 이식
- **farm_002 신규 데이터**: activity_logs, sun_times(36.80_127.70), temp_integration 추가
- **데이터 갱신**: ext_weather, priva_pi, report_snapshots, sun_times, temp_integration, pipeline/state

### IPinsight → smart_farm 이식 패턴
| 패턴 | IPinsight | smart_farm |
|------|-----------|------------|
| 접속마다 명언 | `random.choice()` + session_state | `Math.random()` JS, 매 로드 |
| .gitignore | 로그·DB 제외 | 텔레메트리·대용량바이너리 제외 |
| archive/ | SESSIONS_2026-06.md | SESSIONS_2026-06.md |

---

## 2026-06-16 세션 — 보안·게이트 관리 개선

**커밋 범위**: 5f7e177 → 33aeed8

- 읽기성 POST 게이트 허용 (AI추천·다중시뮬)
- components network-first 전략
- 클러스터 overview PII 익명화 (farm_id 해시)
- watchdog 단일 인스턴스 Mutex 가드

---

## 2026-06-14 이전 — 기반 구축

- 41화면 (온실 G시리즈 + 노지 F시리즈 + 공통 C시리즈)
- ML 모델: 딸기(R²0.805)·오이(MAPE 22.8%)·파프리카·완숙·방울·참외
- PUBLIC_DEMO=1 게이트, SW 캐시 v16
- Cloudflare Named Tunnel (kaasa-smartos) 배포
