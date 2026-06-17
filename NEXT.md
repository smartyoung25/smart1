# NEXT — 다음 세션 시작점
> 생성: 2026-06-17 / 마지막 커밋: 이번 세션

## 현재 상태 (1줄)
41화면·서버 정상 운영. farm_002 신규 데이터 커밋 완료. 농업 명언 순환·.gitignore·archive 도입.

## 이번 세션 목표 (1개만)
[ ] KAMIS 딸기 성수기 단가 전환 확인 or C12 공동출하 화면 기능 보강

## 다음 3개 작업 (우선순위 순)
1. KAMIS 딸기 단가 비수기→성수기 전환 확인 (market 라우터 또는 climatology.py)
2. C12 공동출하 화면 — 채널 비교 로직 점검 및 UI 보강
3. 토마토 M1 ERA5 실측 CSV 확보 후 재학습 (R² 음수 상태)

## 열린 문제 / 블로커
- 토마토 M1: ERA5 실측 CSV 미확보 → 재학습 보류
- out/ 대용량 PPT·DOCX: .gitignore 처리 완료 (별도 드라이브 보관 권장)

## 서버 실행 (복붙용)
```
PYTHONPATH=C:\smart_farm PUBLIC_DEMO=1 python -m uvicorn api.main:app --port 8000
```

## 주의사항
- SW 캐시 현재 v16 — 화면 변경 시 반드시 bump
- PUBLIC_DEMO=1 환경: /api/admin/* 전부 403 (테스트 시 주의)
- P1~P6은 관수 Period (우선순위 아님) — 코드 변경 시 CLAUDE.md 확인
- CLAUDE.md는 아키텍처 변경 시만 읽을 것 (세션 시작 자동 읽기 금지)
