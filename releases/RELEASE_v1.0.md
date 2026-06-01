# KAASA SmartOS v1.0 — 릴리스 노트

> 패키지: `KAASA_SmartOS_v1.0.zip` (146.5 KB) · 2026-06-01

## 구성
- `index.html` — 전체 화면 네비게이터 (/smartos)
- `screens/` — 31개 화면
- `components/base.css` — 공통 디자인 시스템 + 신뢰도 뱃지
- `components/data.js` — KaasaData 연동 레이어 (WS + REST + 폴백)

## 화면 31개
| 모듈 | 화면 |
|------|------|
| 공통 C (16) | C0 회원가입·C1 농장세팅·C2 데이터동의·C3 통합홈·C4 AI진단·C5 ERP·C6 AI학습·C7 학습보상·C8 이기종연동·C9 벤치마킹·C10 투자ROI·C11 공동출하가입·C12 공동출하·c13 AI챗봇·c14 월간리포트·c15 교육 |
| 온실 G (6) | G1 온실홈·G2 환경에너지·G3 관수Period·G4 생육·G5 병해품질·G6 수확유통 |
| 노지 F (7) | F1 노지홈·F2 GIS·F3 기상·F4 토양수분·F5 원격탐사·F6 병해충·F7 노지수확 |
| 개요 (2) | overview·flow |

## 작물 12종
딸기·방울토마토·완숙토마토·참외·파프리카·오이 + 제주(감귤·월동무·당근·양배추·브로콜리·마늘·양파)

## 정책(스마트농업법) 기능 이행
- 6대 영역 통합 모니터링 · 9대 성과지표(목표대비+전월대비 변화율)
- 월간 경영성과 리포트(제5·6·9조) · 교육과정 이수율(제8조)
- 결로·IPM 조기경보 · AI진단·전문가 컨설팅
- **이행→축적→학습→환원 폐루프** (activity→retrain→리포트 학습블록→C7 보상)

## 데이터 신뢰도 표기
🟢 실측 · 🔵 모델 · 🟠 추정 · ⚪ Mock — 전 화면 출처 뱃지

## 실행 방법
1. 백엔드: `python -m uvicorn api.main:app --port 8000` (PostgreSQL+mosquitto 필요)
2. 접속: `http://localhost:8000/smartos`
3. 자동 로그인(admin) → 실데이터 연동

## 외부 키 주입 시 자동 전환 (코드 완비)
- `NAAS_SOIL_API_URL`·`FARMMAP_API_URL` → 노지 토양·필지 실데이터
- `ANTHROPIC_API_KEY` → LLM 챗봇 실응답
- 월별 데이터 누적 → 성과지표 전월대비 변화율

## 검수
33개 화면 동작 · 콘솔 에러 0건 · 하단탭 무결성 · 죽은 링크 0

---

## 성능 측정 (Lighthouse · c3_home · mobile · 2026-06-01)
| 지표 | 결과 | 정책 목표 | 판정 |
|------|------|-----------|------|
| 성능 점수 | 87점 | — | 🟢 양호 |
| 접근성 | 81점 | WCAG AA | 🟡 |
| **LCP** | **1.5s** | < 3.0s | 🟢 PASS |
| FCP | 1.4s | < 1.8s | 🟢 PASS |
| TBT | 110ms | < 200ms | 🟢 PASS |
| SI | 2.1s | — | 🟢 |
| CLS | 0.228 | < 0.1 | 🟠 (데이터 로드 후 KPI 채움으로 이동 — 스켈레톤 적용 시 개선) |

## 실기기 배포
- QR: `releases/qr_smartos.png` → `http://192.168.0.173:8000/smartos`
- 동일 Wi-Fi + 방화벽 8000 포트 허용 필요
- 모바일 브라우저로 QR 스캔 → 자동 로그인 → 실데이터 접속

## GitHub
- 원격: github.com/smartyoung25/smart1 (master)
- 푸시 완료: f6976c0
