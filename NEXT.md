# NEXT — 다음 세션 시작점
> 생성: 2026-06-17 / 갱신: 2026-06-18 / 코드 마지막 커밋: `5009d38`

## 현재 상태 (1줄)
기자재(C16 등록·C17 진단) 평가등급 연계 완성. 회원가입 흐름 단락 해소. 공종 매핑 보강(기타 89%↓). C24 시공업체 찾기. 터널 자동복구 정상. SW v60.

## 이번 세션 목표 (1개만)
[ ] 미정 — 사용자 지시 대기 (기자재·회원가입 흐름 완료, 다음 영역 선택 필요)

## 다음 3개 작업 (후보)
1. 토마토 M1: ERA5 실측 CSV 확보 시 재학습(보류 중 — 사용자 액션)
2. (경미) c2_consent `?next=` URLSearchParams 정식 파싱 교체
3. SMTP/ANTHROPIC_API_KEY .env 설정(사용자 액션 — 메일·LLM 폴백 해제)

## 경미(저우선)
- c2_consent.html `?next=` 디코딩이 `replace(/'/g,'')`로 작은따옴표 제거(영숫자 farm_id엔 무해) → URLSearchParams 정식 파싱으로 교체 여지

## 이번 세션 완료 (2026-06-18)
- **참조 DB v1** (`18457e5`): 스마트팜코리아 공식 DB — 자사제품 312·기업 623·시공업체 97 + 빌더
- **C16 자동완성 v1** (`f91d522`): /api/reference + 제조사·모델 datalist
- **C24 시공업체 찾기** (`d5ce553`): 도급순위·지역 검색 화면
- **watchdog 복구** (`0e03351`): UTF-8 BOM 저장(PS5.1 cp949 오독 해결) + Test-Tunnel 외부연결 감시
- **카탈로그 v2** (`dc85912`): 평가완료 3071제품·공종별 분류·11항목 5등급 + 빌더
- **C16 분류 재설계** (`ebfcee1`): 대분류→기종 + 카탈로그 종합등급 자동완성
- **업로드 자동 재분류** (`72f6cf6`): 견적서/시방서 → 카탈로그 매칭 → 등급·공종 부여
- **작업 문서** (`7505a57`): 작업내역서·작업계획서 docx(docs/worklog/)
- **C16 흐름 직관화** (`ebf0637`): 2히어로 진입·검색우선 등록·장비ID자동·등급배지 + refHit 분류 클로버 버그수정
- **보유장비 평가 요약** (`bdaeba7`): 평균등급·분포·개선우선순위→C17 + 데모 카탈로그 실제품 5종 시드
- **OCR/PDF 매칭 정확도** (`c1c1ee8`): PDF 텍스트 폴백·OCR 제조사모델 분리·매칭 정규화('엠에스'='(주)엠에스')
- **회원가입 흐름 단락 해소** (`472a8f2`): register farm_id 발급→sf_farm_id 인계→C1 동일 farm_id 사용 / 온보딩 JWT farm_id 권위(IDOR 차단) / 로그인 시 onboarding_required면 C1 라우팅
- **전체 흐름 점검·온실 CTA** (`1bb6e37`): 정적+런타임(46/46 정상)+에이전트 점검, 온실 g2→g6 다음단계 CTA·C17 빈target 가드
- **카탈로그 공종 매핑 보강** (`cb887d7`): 기종명 키워드 추론으로 공종 "기타" 2964→336(89%↓)
- **C17 보유 기자재 평가 카드** (`5009d38`): 평균등급·A~E 분포·교체 우선순위 정식 연계(C16 산식 동일)

## 열린 문제 / 블로커
- 토마토 M1: ERA5 실측 CSV 미확보 → 재학습 보류
- ~~카탈로그 공종 "기타" 2964건~~ ✅ 해결(`cb887d7`, 기종명 키워드 추론 → 336건)
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
- SW 캐시 현재 **v60** — 화면 변경 시 반드시 bump
- PUBLIC_DEMO=1 환경: /api/admin/* 전부 403 / /api/reference/* 는 공개 읽기(허용)
- /api/reference 는 auth.py `_PUBLIC_PATHS` 에 등록됨 (비인증 GET)
- CLAUDE.md는 아키텍처 변경 시만 읽을 것
