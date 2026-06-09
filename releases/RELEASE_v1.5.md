# KAASA SmartOS v1.5 릴리스 노트

**테마**: 실데이터 주입 + 데이터 시각화·UX 프레임워크 강화 (2026-06-09 PM)

## v1.4 → v1.5 변경
### 실데이터 주입 (제주, PII 제외 집계·지역매칭 자동전환)
- 흙토람 토양검정 13,842필지 → `/field/soil`(naas_soil_real)
- 팜맵 농경지지도 276,491필지 → `/field/parcels`·F8(farmmap_real)
- 농진청 소득조사 102농가 → `/benchmark` 실비교군(소득률 상위25% 66.2%)
- 병해충 예찰 파이프라인(`/field/pest`) 완성(데이터 적재 시 활성)
- importer: `scripts/import_real_{soil,parcels,income,pest}.py`

### 데이터 시각화 10건 (의존성 0 SVG/CSS)
C3 우수농가바·실데이터배지 / C17 6대영역 레이더 / F8 NDVI히트맵 / G3 일일WC곡선 /
C14 전월대비 다이버징 / G2 온습도·VPD추이 / G6 신뢰구간밴드 / F3 16일 기온·강수 / G4 초장추세

### 프레임워크 통일·UX (base.css/data.js 전역)
- 차트 팔레트 토큰(--chart-*) — 온실·노지·공통 동일 색의미
- 접근성: 포커스 링·모션 감소·터치 40px
- 효과성·효율성: 촉각 피드백·헤더 40×40·앵커 정확도·hover
- 전역 오프라인/연결 감지 배너

## 전체 현황 (41화면)
- 공통 C0~C20 + 온실 G1~G6 + 노지 F1~F8 + 결과보고서 PDF 2종 + 개요/인트로
- 진단·역량·클러스터·경영전략·실데이터 전 폐루프 연결

## 품질·보안
- **41화면 콘솔에러·API4xx·깨진링크 0건 · 백엔드 22엔드포인트 200 OK · FCP ~0.5s**
- **PUBLIC_DEMO 읽기전용 보안 게이트 검증**: 읽기 200 / 쓰기 403 / 관리자 403 / 로그인 OK

## 공개 배포 절차 (임시 공개 테스트)
1. (보안) 읽기전용 + JWT 회전으로 기동:
   ```
   set PUBLIC_DEMO=1
   set JWT_SECRET_KEY=<무작위>
   python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
   ```
2. (공개) Cloudflare 빠른 터널 — `cloudflared` 설치 후:
   ```
   deploy\cloudflare\demo_live.bat   (또는 setup_tunnel.bat)
   cloudflared tunnel --url http://localhost:8000
   ```
   → 발급된 `https://*.trycloudflare.com` URL로 임시 공개. 계정 불필요.
3. 종료 시 PUBLIC_DEMO 해제 + 터널 종료.

※ 공인 도메인·상시 HTTPS는 `deploy/` 스크립트(DuckDNS·Let's Encrypt·systemd) 참조.
