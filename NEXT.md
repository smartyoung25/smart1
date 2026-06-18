# NEXT — 다음 세션 시작점
> 생성: 2026-06-17 / 갱신: 2026-06-18 / 마지막 커밋: `be82bfb` (코드 마지막: `72f6cf6`)

## 현재 상태 (1줄)
기자재(C16) 공종별 분류 재설계 + 평가완료 카탈로그(3071제품·A~E등급) 자동완성 + 업로드 자동 재분류 완료. C24 시공업체 찾기 신설. 터널 자동복구(watchdog BOM·외부연결 감시) 정상.

## 이번 세션 목표 (1개만)
[ ] C16 등록 목록 카드에 종합등급 배지 표시 (보유장비 평균 등급 가시화)

## 다음 3개 작업 (우선순위 순)
1. C16 등록 목록(_renderList)에 gubun·grade·gong 배지 추가
2. 농가 보유장비 평균 등급 리포트 → C17 진단 카드 연계
3. PDF/도면 업로드 OCR 매칭 정확도 보강 (현재 엑셀/CSV 매칭만 검증됨)

## 이번 세션 완료 (2026-06-18)
- **참조 DB v1** (`18457e5`): 스마트팜코리아 공식 DB — 자사제품 312·기업 623·시공업체 97 + 빌더
- **C16 자동완성 v1** (`f91d522`): /api/reference + 제조사·모델 datalist
- **C24 시공업체 찾기** (`d5ce553`): 도급순위·지역 검색 화면
- **watchdog 복구** (`0e03351`): UTF-8 BOM 저장(PS5.1 cp949 오독 해결) + Test-Tunnel 외부연결 감시
- **카탈로그 v2** (`dc85912`): 평가완료 3071제품·공종별 분류·11항목 5등급 + 빌더
- **C16 분류 재설계** (`ebfcee1`): 대분류→기종 + 카탈로그 종합등급 자동완성
- **업로드 자동 재분류** (`72f6cf6`): 견적서/시방서 → 카탈로그 매칭 → 등급·공종 부여

## 열린 문제 / 블로커
- 토마토 M1: ERA5 실측 CSV 미확보 → 재학습 보류
- 카탈로그 공종별 구분: 2964/3071 이 "기타" (원본 DB 한계 — 공종 매핑 보강 여지)
- watchdog .ps1 편집 시 반드시 UTF-8 **BOM** 유지 (BOM 없으면 PS5.1에서 한글 깨져 죽음)

## 참조 데이터 재생성 (지속 업그레이드)
```
python scripts/build_equipment_catalog.py --src "<새 평가본.xlsx>"      # 카탈로그 v2
python scripts/build_equipment_reference.py --src "<스마트팜코리아 DB.xlsx>"  # 참조 v1
```

## 서버 실행 (복붙용)
```
PYTHONPATH=C:\smart_farm PUBLIC_DEMO=1 python -m uvicorn api.main:app --port 8000
cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos
```

## 주의사항
- SW 캐시 현재 **v55** — 화면 변경 시 반드시 bump
- PUBLIC_DEMO=1 환경: /api/admin/* 전부 403 / /api/reference/* 는 공개 읽기(허용)
- /api/reference 는 auth.py `_PUBLIC_PATHS` 에 등록됨 (비인증 GET)
- CLAUDE.md는 아키텍처 변경 시만 읽을 것
