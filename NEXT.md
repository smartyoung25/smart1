# NEXT — 다음 세션 시작점
> 생성: 2026-06-14 / 마지막 커밋: 659a7f2 feat: 데모 게이트 관리자 조회+안전변경 활성화

## 현재 상태 (1줄)
41화면·서버 정상 운영 중. farm_003 신규 농가 데이터 미커밋 상태 (의도적 보류 여부 확인 필요)

## 이번 세션 목표 (1개만)
[ ] farm_003 미커밋 파일 처리 결정 (커밋 or 정리) 후 다음 기능 착수

## 다음 3개 작업 (우선순위 순)
1. `git status` 확인 → farm_003 관련 파일 커밋 or 스킵 결정
2. tests/test_connectors.py (untracked) — 실행 후 통과 확인
3. 다음 기능: C12 공동출하 화면 or KAMIS 딸기 비수기→성수기 단가 전환 확인

## 열린 문제 / 블로커
- farm_003 신규 데이터 파일 9개 (untracked): 의도적 보류인지, 아니면 커밋 누락인지 확인 필요
- api/data/telemetry/2026-06-12~13.jsonl — 텔레메트리 로그 누적 (커밋 대상 아닌 로그성)

## 서버 실행 (복붙용)
```
PYTHONPATH=C:\smart_farm PUBLIC_DEMO=1 python -m uvicorn api.main:app --port 8000
```

## 주의사항
- SW 캐시 현재 v16 — 화면 변경 시 반드시 bump
- PUBLIC_DEMO=1 환경: /api/admin/* 전부 403 (테스트 시 주의)
- P1~P6은 관수 Period (우선순위 아님) — 코드 변경 시 CLAUDE.md 확인
- CLAUDE.md는 아키텍처 변경 시만 읽을 것 (세션 시작 자동 읽기 금지)
