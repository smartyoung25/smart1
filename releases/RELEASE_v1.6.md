# KAASA SmartOS v1.6 릴리스 노트

**테마**: 공개 배포 + 자체호스팅 모니터링 + 견고성 (2026-06-09 PM)

## v1.5 → v1.6 변경
- **공개 배포 완료**: Cloudflare 퀵터널(읽기전용 PUBLIC_DEMO + JWT 회전) — 외부 HTTPS 접속·로그인·조회 검증
- **자체호스팅 모니터링(C)**: `/api/telemetry/client` 수집 + `/api/telemetry/summary` 집계 + data.js 전역 에러 비콘 (Sentry 대체, 외부계정 불필요)
- **견고성**: C20 관제 admin 403 graceful 처리, 전역 오프라인 배너
- **UX/시각화**(v1.5): 10개 차트 + 차트 토큰 통일 + 접근성 + 촉각/터치/스크롤

## 상용화 잔여 갭 (사용자 자격증명·데이터 필요)
| # | 항목 | 상태 | 필요 |
|---|------|------|------|
| A | 결제 연동 | 제외(지시) | — |
| **B** | 상시 공인 도메인 + HTTPS | `deploy/` 스크립트(DuckDNS·Let's Encrypt·systemd·Cloudflare) 준비 완료 | **도메인 구매**(사용자) |
| **C** | 모니터링 | ✅ **완료**(자체 텔레메트리) | — |
| **D** | 외부 실데이터 키(NAAS·위성·LLM·알림) | 어댑터·자동전환 구조 완비 | **API 키 주입**(사용자) — `docs/INTEGRATION_GUIDE.md` |
| **E** | ML 재학습 | 파이프라인 有 | **농가단위 수확량+환경 시계열**(데이터) |

## 품질·보안
- 41화면 · 백엔드 22+엔드포인트 200 OK · FCP ~0.5s
- PUBLIC_DEMO 읽기전용(쓰기·관리자 403) 검증, JWT 회전
- 제주 실데이터 3종(흙토람·팜맵·소득조사) 주입·검증

## 배포 절차
- 임시 공개: `deploy/cloudflare/demo_live.bat` (cloudflared 퀵터널)
- 상시(B): 도메인 확보 후 `deploy/cloudflare/setup_tunnel.bat` + config.yml(named tunnel) 또는 systemd+nginx+Let's Encrypt
