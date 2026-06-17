# smart_farm 세션 아카이브 — 2026년 6월

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
