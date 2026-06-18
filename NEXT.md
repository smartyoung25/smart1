# NEXT — 다음 세션 시작점
> 생성: 2026-06-18 / 마지막 커밋: `e1109fc` PII 제거

## 현재 상태 (1줄)
기자재·회원가입·카탈로그·보안 완료. Stop 훅(세션 종료 시 NEXT.md 자동갱신) 추가. SW v61.

## 이번 세션 목표 (1개만)
[ ] 미정 — 사용자 지시 대기

## 다음 3개 작업 (우선순위 순)
1. KAMIS 딸기 단가 비수기→성수기 전환 확인 (market 라우터 또는 climatology.py)
2. C12 공동출하 채널 비교 로직 점검 및 UI 보강
3. 토마토 M1: ERA5 실측 CSV 확보 후 재학습 (R² 음수 — 사용자 액션 필요)

## 열린 문제 / 블로커
- **LLM 챗봇**: Anthropic 크레딧 잔액 부족 → 규칙기반 폴백 (충전 시 즉시 전환)
- **SMTP**: SMTP_USER·SMTP_PASSWORD 미설정 → 메일 발송 불가 (Gmail 앱비번 16자 필요 + 서버 재기동)
- 토마토 M1: ERA5 CSV 미확보 → 재학습 보류
- watchdog .ps1 편집 시 UTF-8 **BOM** 유지 필수

## 서버 실행 (복붙용)
```
PYTHONPATH=C:\smart_farm PUBLIC_DEMO=1 python -m uvicorn api.main:app --port 8000
cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos
```

## 주의사항
- SW 캐시 현재 **v61** — 화면 변경 시 반드시 bump
- PUBLIC_DEMO=1: /api/admin/* 전부 403
- CLAUDE.md는 아키텍처 변경 시만 읽을 것
