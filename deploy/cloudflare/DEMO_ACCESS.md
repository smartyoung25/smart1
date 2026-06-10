# 무료 공개 데모 접속 안내 (확정: 퀵터널)

## 현재 공개 URL
```
https://distributed-financing-worldcat-uploaded.trycloudflare.com
```
- `/intro` 랜딩 · `/smartos` 전체 네비게이터 · 읽기전용(PUBLIC_DEMO) · PWA 설치형

## ⚠️ 퀵터널 특성 — URL은 재시작 시 변경됨
무료 퀵터널은 **터널 프로세스가 재시작되면 새 무작위 URL**이 발급됩니다.
따라서 **고정 링크가 아니며**, 최신 URL은 항상 아래에서 확인:
```
deploy\cloudflare\current_url.txt        ← 실행 중 최신 공개 URL 자동 기록
```

## 끊김 없이 유지하려면 (자동 재기동)
```
powershell -ExecutionPolicy Bypass -File deploy\cloudflare\quicktunnel_resilient.ps1
```
→ 터널이 죽으면 자동 재기동 + 새 URL을 `current_url.txt`에 기록.
(단 URL 자체는 바뀌므로, 변치 않는 주소가 필요하면 커스텀 도메인 필요 — `named_tunnel_runbook.md`)

## 고정 주소가 필요해지면 (업그레이드)
- 보유 도메인 + Cloudflare → Named Tunnel (포트포워딩 불필요, 고정 URL)
- 또는 DuckDNS 토큰 + 포트포워딩 → `<sub>.duckdns.org`
참조: `deploy/cloudflare/named_tunnel_runbook.md`, `deploy/duckdns/README.md`

## 보안 (공개 중 적용)
- PUBLIC_DEMO=1: 쓰기·관리자 API 403 차단(읽기 전용)
- JWT_SECRET 무작위 회전 · 클라이언트 에러 텔레메트리 수집
